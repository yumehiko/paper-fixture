#!/usr/bin/env python3
"""Export paper-fixture geometry and front-print evidence from a native AI file.

The Illustrator DOM is the source for all geometry and print paths.  A separate
material JSON is optional because the current AI convention has no thickness
field; its provenance is retained in the exported package.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

MM_PER_PT = 25.4 / 72.0
SCHEMA = "paper-fixture-illustrator-export-v1"


class ExportValidationError(ValueError):
    """An AI input violates the explicit paper-fixture export convention."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _note_id(path: dict[str, Any]) -> str:
    note = path.get("note")
    if not isinstance(note, str) or not note.startswith("py-ai-path:"):
        raise ExportValidationError(
            f"path {path.get('name')!r} has no py-ai-path identifier note"
        )
    try:
        value = json.loads(note.removeprefix("py-ai-path:"))
    except json.JSONDecodeError as error:
        raise ExportValidationError(f"path {path.get('name')!r} has invalid identifier note") from error
    item_id = value.get("id") if isinstance(value, dict) else None
    if not isinstance(item_id, str) or not item_id:
        raise ExportValidationError(f"path {path.get('name')!r} has an empty identifier")
    return item_id


def _finite_pair(value: Any, *, path_id: str, field: str) -> tuple[float, float]:
    if not isinstance(value, list) or len(value) != 2:
        raise ExportValidationError(f"{path_id}: {field} must be a two-number coordinate")
    try:
        x, y = float(value[0]), float(value[1])
    except (TypeError, ValueError) as error:
        raise ExportValidationError(f"{path_id}: {field} must be numeric") from error
    if not math.isfinite(x) or not math.isfinite(y):
        raise ExportValidationError(f"{path_id}: {field} must be finite")
    return x, y


def _point(point: dict[str, Any], *, path_id: str, top_pt: float, left_pt: float) -> dict[str, Any]:
    anchor_x, anchor_y = _finite_pair(point.get("anchor"), path_id=path_id, field="anchor")
    left_x, left_y = _finite_pair(point.get("left_direction"), path_id=path_id, field="left_direction")
    right_x, right_y = _finite_pair(point.get("right_direction"), path_id=path_id, field="right_direction")

    def convert(x: float, y: float) -> list[float]:
        return [(x - left_pt) * MM_PER_PT, (top_pt - y) * MM_PER_PT]

    return {
        "anchor_mm": convert(anchor_x, anchor_y),
        "in_handle_mm": convert(left_x, left_y),
        "out_handle_mm": convert(right_x, right_y),
        "point_type": point.get("point_type"),
    }


def _path_kind(path_id: str) -> tuple[str, str, str]:
    segments = path_id.split(".")
    if len(segments) < 3 or segments[0] not in {"cut", "print"}:
        raise ExportValidationError(
            f"{path_id}: id must be cut.<PART>.<ROLE> or print.<PART>.<ROLE>"
        )
    return segments[0], segments[1], ".".join(segments[2:])


def _bbox(paths: list[dict[str, Any]]) -> list[float]:
    points = [point["anchor_mm"] for path in paths for point in path["points"]]
    if not points:
        raise ExportValidationError("cannot calculate a bounding box without path anchors")
    xs, ys = [point[0] for point in points], [point[1] for point in points]
    return [min(xs), min(ys), max(xs), max(ys)]


def _normalize_path(raw: dict[str, Any], *, top_pt: float, left_pt: float) -> dict[str, Any]:
    path_id = _note_id(raw)
    anchors = raw.get("anchors")
    if not isinstance(anchors, list) or len(anchors) < 3:
        raise ExportValidationError(f"{path_id}: a closed printable/cut path needs at least three anchors")
    if raw.get("closed") is not True:
        raise ExportValidationError(f"{path_id}: path must be closed")
    normalized = {
        "source_id": path_id,
        "name": raw.get("name"),
        "closed": True,
        "filled": raw.get("filled") is True,
        "stroked": raw.get("stroked") is True,
        "fill_color": raw.get("fill_color"),
        "stroke_color": raw.get("stroke_color"),
        "stroke_width_mm": float(raw.get("stroke_width", 0.0)) * MM_PER_PT,
        "points": [_point({"anchor": item.get("anchor"), "left_direction": item.get("left_direction", item.get("left")), "right_direction": item.get("right_direction", item.get("right")), "point_type": item.get("point_type")}, path_id=path_id, top_pt=top_pt, left_pt=left_pt) for item in anchors],
    }
    parent = raw.get("parent")
    if isinstance(parent, dict):
        normalized["parent"] = parent
    return normalized


def export_from_dom(dom: dict[str, Any], *, source: Path, material: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize a *live Illustrator DOM result* into the portable export schema."""

    illustrator = dom.get("illustrator")
    if not isinstance(illustrator, dict) or illustrator.get("ok") is not True:
        raise ExportValidationError("Illustrator did not return a successful live DOM inspection")
    layers = illustrator.get("layer_names")
    if not isinstance(layers, list) or not {"PF_CUT", "PF_PRINT_FRONT"}.issubset(layers):
        raise ExportValidationError("required layers PF_CUT and PF_PRINT_FRONT are missing")
    artboards = illustrator.get("artboards")
    if not isinstance(artboards, list) or len(artboards) != 1:
        raise ExportValidationError("exactly one artboard is required for one export package")
    rect = artboards[0].get("rect") if isinstance(artboards[0], dict) else None
    if not isinstance(rect, list) or len(rect) != 4:
        raise ExportValidationError("artboard rectangle is unavailable from Illustrator")
    left, top, right, bottom = (float(value) for value in rect)
    if right <= left or top <= bottom:
        raise ExportValidationError("artboard rectangle is not a positive area")
    raw_paths = illustrator.get("paths")
    if not isinstance(raw_paths, list):
        raise ExportValidationError("Illustrator did not return path inspection data")

    parts: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: {"cut": [], "print": []})
    group_layers = illustrator.get("group_layers")
    if not isinstance(group_layers, dict):
        raise ExportValidationError("Illustrator did not return group-to-layer membership data")
    seen_ids: set[str] = set()
    for raw in raw_paths:
        if not isinstance(raw, dict):
            raise ExportValidationError("Illustrator returned a non-object path")
        path_id = _note_id(raw)
        if path_id in seen_ids:
            raise ExportValidationError(f"duplicate path identifier: {path_id}")
        seen_ids.add(path_id)
        layer, part_id, role = _path_kind(path_id)
        item = _normalize_path(raw, top_pt=top, left_pt=left)
        expected_group = f"PF_PART_{part_id}"
        parent = item.get("parent")
        if not isinstance(parent, dict) or parent.get("type") != "GroupItem" or parent.get("name") != expected_group:
            raise ExportValidationError(f"{path_id}: must be directly inside group {expected_group}")
        expected_layer = "PF_CUT" if layer == "cut" else "PF_PRINT_FRONT"
        group_key = f"{expected_layer}:{expected_group}"
        if group_layers.get(group_key) != expected_layer:
            raise ExportValidationError(f"{path_id}: group {expected_group} is not directly on {expected_layer}")
        item["role"] = role
        parts[part_id][layer].append(item)

    exported_parts: list[dict[str, Any]] = []
    for part_id in sorted(parts):
        part = parts[part_id]
        outers = [item for item in part["cut"] if item["role"] == "outer"]
        holes = [item for item in part["cut"] if item["role"].startswith("hole.")]
        unsupported = [item["source_id"] for item in part["cut"] if item not in outers + holes]
        if len(outers) != 1:
            raise ExportValidationError(f"{part_id}: exactly one cut.<PART>.outer is required")
        if unsupported:
            raise ExportValidationError(f"{part_id}: unsupported cut roles: {', '.join(unsupported)}")
        if not part["print"]:
            raise ExportValidationError(f"{part_id}: PF_PRINT_FRONT paths are missing")
        # AI may intentionally retain a non-printing cut path without a visible
        # stroke.  Geometry import needs the closed, unfilled contour; whether a
        # CAM-facing stroke is required belongs to a later output profile.
        if outers[0]["filled"]:
            raise ExportValidationError(f"{part_id}: outer contour must be unfilled")
        if any(item["filled"] for item in holes):
            raise ExportValidationError(f"{part_id}: hole contours must be unfilled")
        outer_bounds = _bbox(outers)
        if outer_bounds[2] <= outer_bounds[0] or outer_bounds[3] <= outer_bounds[1]:
            raise ExportValidationError(f"{part_id}: outer contour has no positive extent")
        exported_parts.append(
            {
                "id": part_id,
                "cut": {"outer": outers[0], "holes": holes},
                "dimensions_mm": [outer_bounds[2] - outer_bounds[0], outer_bounds[3] - outer_bounds[1]],
                "placement_bounds_mm": outer_bounds,
                "print_front": {"paths": part["print"], "bounds_mm": _bbox(part["print"])},
            }
        )

    if not exported_parts:
        raise ExportValidationError("no PF part paths were found in Illustrator")
    material_result: dict[str, Any]
    if material is None:
        material_result = {"status": "missing", "error": "material JSON is required; thickness is not encoded in this AI convention"}
    else:
        thickness = material.get("thickness_mm")
        if not isinstance(thickness, (int, float)) or isinstance(thickness, bool) or not math.isfinite(thickness) or thickness <= 0:
            raise ExportValidationError("material.thickness_mm must be a finite positive number")
        material_result = {
            "status": "external-explicit-input",
            "thickness_mm": float(thickness),
            "front_side": material.get("front_side", "PF_PRINT_FRONT"),
            "back_and_edge": material.get("back_and_edge", "paper base color in later stage"),
        }

    return {
        "schema": SCHEMA,
        "source": {"path": str(source.resolve()), "sha256": _sha256(source), "read_via": "Illustrator 2026 live DOM"},
        "coordinate_system": {
            "unit": "mm",
            "origin": "artboard upper-left",
            "x_axis": "right",
            "y_axis": "down",
            "source_unit": "Illustrator points",
            "mm_per_point": MM_PER_PT,
            "artboard_bounds_mm": [0.0, 0.0, (right - left) * MM_PER_PT, (top - bottom) * MM_PER_PT],
        },
        "material": material_result,
        "print": {"side": "front", "range_mm": [0.0, 0.0, (right - left) * MM_PER_PT, (top - bottom) * MM_PER_PT], "pixel_mapping": "pixel_x = x_mm / width_mm * PNG_width; pixel_y = y_mm / height_mm * PNG_height"},
        "parts": exported_parts,
    }


def inspect_ai(source: Path, *, timeout: float) -> dict[str, Any]:
    """Read the existing file in Illustrator, without relying on its PDF/IR payload.

    The dependency exposes generic read-only DOM snapshot helpers but not a
    public full-path export endpoint.  This small adapter only asks Illustrator
    for that already-supported snapshot plus direct group/layer membership; it
    performs no AI parsing or writing.
    """
    if platform.system() != "Darwin":
        raise RuntimeError("Illustrator live DOM export is supported on macOS only")
    try:
        from py_ai_illustrator._illustrator_bridge import execute_javascript
        from py_ai_illustrator._illustrator_scripts import _native_local_dom_helpers, character_code_expression
    except ImportError as error:
        raise RuntimeError("py-ai-illustrator is required; install its documented environment") from error
    source_literal = character_code_expression(source.resolve())
    javascript = f'''#target illustrator
(function () {{
 var source = new File({source_literal}); var documentRef = null;
 var previousInteractionLevel = app.userInteractionLevel;
{_native_local_dom_helpers()}
 try {{
  app.userInteractionLevel = UserInteractionLevel.DONTDISPLAYALERTS;
  if (!source.exists) throw new Error("source does not exist");
  documentRef = app.open(source);
  var groups = [];
  for (var index = 0; index < documentRef.groupItems.length; index++) {{
   var group = documentRef.groupItems[index];
   groups.push({{name: group.name || "", parent: itemParent(group)}});
  }}
  return toJson({{ok: true, illustrator_version: app.version,
   snapshot: documentSnapshot(documentRef), groups: groups}});
 }} catch (error) {{ return toJson({{ok: false, error: String(error)}}); }}
 finally {{ if (documentRef !== null) documentRef.close(SaveOptions.DONOTSAVECHANGES);
  app.userInteractionLevel = previousInteractionLevel; }}
}})();'''
    with tempfile.TemporaryDirectory(prefix="paper-fixture-export-") as directory:
        completed = execute_javascript(javascript, Path(directory), timeout=timeout, application_name="Adobe Illustrator", script_name="paper-fixture-export-read.jsx")
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "Illustrator AppleScript failed")
    try:
        runtime = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError("Illustrator returned non-JSON export evidence") from error
    if not isinstance(runtime, dict) or runtime.get("ok") is not True:
        raise RuntimeError(f"Illustrator inspection failed: {runtime}")
    snapshot = runtime.get("snapshot")
    if not isinstance(snapshot, dict):
        raise RuntimeError("Illustrator did not return a document snapshot")
    structure = snapshot.get("structure")
    if not isinstance(structure, dict):
        raise RuntimeError("Illustrator did not return document structure")
    groups = runtime.get("groups")
    group_layers: dict[str, str] = {}
    if not isinstance(groups, list):
        raise RuntimeError("Illustrator did not return group memberships")
    for group in groups:
        if not isinstance(group, dict):
            continue
        name, parent = group.get("name"), group.get("parent")
        if isinstance(name, str) and isinstance(parent, dict) and parent.get("type") == "Layer" and isinstance(parent.get("name"), str):
            group_layers[f"{parent['name']}:{name}"] = parent["name"]
    return {"status": "passed", "illustrator": {"ok": True, "illustrator_version": runtime.get("illustrator_version"), "layer_names": [item.get("name") for item in structure.get("layers", []) if isinstance(item, dict)], "artboards": structure.get("artboards"), "paths": snapshot.get("paths"), "group_layers": group_layers}}


def export_print_front_png(source: Path, output: Path, *, timeout: float) -> dict[str, Any]:
    """Rasterize only PF_PRINT_FRONT in Illustrator; no source file is saved."""
    try:
        from py_ai_illustrator._illustrator_bridge import execute_javascript
        from py_ai_illustrator._illustrator_scripts import character_code_expression
    except ImportError as error:
        raise RuntimeError("py-ai-illustrator is required; install its documented environment") from error
    source_literal, output_literal = character_code_expression(source.resolve()), character_code_expression(output.resolve())
    javascript = f'''#target illustrator
(function () {{
 var source = new File({source_literal}); var output = new File({output_literal});
 var documentRef = null; var previousInteractionLevel = app.userInteractionLevel;
 try {{
  app.userInteractionLevel = UserInteractionLevel.DONTDISPLAYALERTS;
  documentRef = app.open(source);
  var found = false; var hidden = [];
  for (var index = 0; index < documentRef.layers.length; index++) {{
   var layer = documentRef.layers[index]; var wanted = layer.name === "PF_PRINT_FRONT";
   if (wanted) found = true; else hidden.push(layer.name);
   layer.visible = wanted;
  }}
  if (!found) throw new Error("PF_PRINT_FRONT layer is missing");
  var options = new ExportOptionsPNG24(); options.artBoardClipping = true;
  options.antiAliasing = true; options.transparency = true;
  options.horizontalScale = 200; options.verticalScale = 200;
  documentRef.exportFile(output, ExportType.PNG24, options);
  return "ok:PF_PRINT_FRONT:" + hidden.join("|");
 }} catch (error) {{ return "error:" + String(error); }}
 finally {{ if (documentRef !== null) documentRef.close(SaveOptions.DONOTSAVECHANGES);
  app.userInteractionLevel = previousInteractionLevel; }}
}})();'''
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="paper-fixture-print-export-") as directory:
        completed = execute_javascript(javascript, Path(directory), timeout=timeout, application_name="Adobe Illustrator", script_name="paper-fixture-print-export.jsx")
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "Illustrator print export failed")
    response = completed.stdout.strip()
    prefix = "ok:PF_PRINT_FRONT:"
    if not response.startswith(prefix) or not output.is_file():
        raise RuntimeError(f"Illustrator print export failed: {response}")
    hidden = response.removeprefix(prefix)
    return {"visible_layer": "PF_PRINT_FRONT", "hidden_layers": hidden.split("|") if hidden else [], "path": str(output), "dpi": 144}


def _load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ExportValidationError(f"cannot read JSON {path}: {error}") from error
    if not isinstance(data, dict):
        raise ExportValidationError(f"{path}: JSON object required")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--material", type=Path, help="explicit external material data; required for a complete package")
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args(argv)
    if not args.source.is_file():
        parser.error(f"source does not exist: {args.source}")
    if args.output_dir.exists():
        parser.error(f"refusing to overwrite existing output directory: {args.output_dir}")
    try:
        material = _load_json(args.material) if args.material else None
        package = export_from_dom(inspect_ai(args.source, timeout=args.timeout), source=args.source, material=material)
        args.output_dir.mkdir(parents=True)
        (args.output_dir / "export.json").write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        # The native PDF-compatible AI is rasterized again, keeping a reproducible
        # all-artboard review PNG alongside the semantic print range declaration.
        from py_ai_illustrator.verification import render_preview
        preview = render_preview(args.source, args.output_dir / "artboard.preview.png", timeout=args.timeout, overwrite=False).to_dict()
        print_png = export_print_front_png(args.source, args.output_dir / "print-front.png", timeout=args.timeout)
        (args.output_dir / "evidence.json").write_text(json.dumps({"dom": inspect_ai(args.source, timeout=args.timeout), "preview": preview, "print_front_png": print_png}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (ExportValidationError, RuntimeError, ValueError) as error:
        print(f"export error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
