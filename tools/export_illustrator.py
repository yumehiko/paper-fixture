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


def _bbox(paths: list[dict[str, Any]]) -> list[float]:
    points = [point["anchor_mm"] for path in paths for point in path["points"]]
    if not points:
        raise ExportValidationError("cannot calculate a bounding box without path anchors")
    xs, ys = [point[0] for point in points], [point[1] for point in points]
    return [min(xs), min(ys), max(xs), max(ys)]


def _normalize_path(raw: dict[str, Any], *, source_id: str, top_pt: float, left_pt: float, closed: bool = True) -> dict[str, Any]:
    anchors = raw.get("anchors")
    if not isinstance(anchors, list) or len(anchors) < 3:
        raise ExportValidationError(f"{source_id}: a closed printable/cut path needs at least three anchors")
    if raw.get("closed") is not closed:
        raise ExportValidationError(f"{source_id}: path must be {'closed' if closed else 'open'}")
    normalized = {
        "source_id": source_id,
        "name": raw.get("name"),
        "closed": closed,
        "filled": raw.get("filled") is True,
        "stroked": raw.get("stroked") is True,
        "fill_color": raw.get("fill_color"),
        "stroke_color": raw.get("stroke_color"),
        "stroke_width_mm": float(raw.get("stroke_width", 0.0)) * MM_PER_PT,
        "points": [_point({"anchor": item.get("anchor"), "left_direction": item.get("left_direction", item.get("left")), "right_direction": item.get("right_direction", item.get("right")), "point_type": item.get("point_type")}, path_id=source_id, top_pt=top_pt, left_pt=left_pt) for item in anchors],
    }
    parent = raw.get("parent")
    if isinstance(parent, dict):
        normalized["parent"] = parent
    return normalized


def _part_id(group_name: Any) -> str | None:
    if not isinstance(group_name, str) or not group_name.startswith("PF_PART_"):
        return None
    value = group_name.removeprefix("PF_PART_")
    return value or None


def _flatten_path(path: dict[str, Any], steps: int = 32) -> list[list[float]]:
    points = path["points"]
    result = []
    for index, current in enumerate(points):
        previous = points[index - 1]
        p0, p1, p2, p3 = previous["anchor_mm"], previous["out_handle_mm"], current["in_handle_mm"], current["anchor_mm"]
        for step in range(steps):
            t = step / steps; u = 1 - t
            result.append([u**3*p0[0]+3*u*u*t*p1[0]+3*u*t*t*p2[0]+t**3*p3[0], u**3*p0[1]+3*u*u*t*p1[1]+3*u*t*t*p2[1]+t**3*p3[1]])
    return result


def _point_in_polygon(point: list[float], polygon: list[list[float]], tolerance: float = 1e-5) -> bool:
    """Use anchor polygons only to classify already-closed Illustrator paths.

    Curved outline segments remain in the exported Bézier geometry.  The test is
    deliberately conservative: ambiguous nesting is rejected rather than
    silently assigning a cut path to an outer contour or hole.
    """
    x, y = point
    inside = False
    for index, first in enumerate(polygon):
        second = polygon[(index + 1) % len(polygon)]
        dx, dy = second[0] - first[0], second[1] - first[1]
        length = math.hypot(dx, dy)
        if length and abs(dx * (y - first[1]) - dy * (x - first[0])) / length <= tolerance and min(first[0], second[0]) - tolerance <= x <= max(first[0], second[0]) + tolerance and min(first[1], second[1]) - tolerance <= y <= max(first[1], second[1]) + tolerance:
            raise ExportValidationError("PF_CUT contour containment is ambiguous at a boundary")
        if (first[1] > y) != (second[1] > y):
            crossing = (second[0] - first[0]) * (y - first[1]) / (second[1] - first[1]) + first[0]
            if x < crossing:
                inside = not inside
    return inside


def _is_straight_fold(path: dict[str, Any], label: str) -> tuple[list[float], list[float]]:
    anchors = path.get("anchors")
    if path.get("closed") is not False or path.get("filled") is True or not isinstance(anchors, list) or len(anchors) != 2:
        raise ExportValidationError(f"{label}: PF_FOLD path must be an unfilled open line with exactly two anchors")
    first, second = (_finite_pair(item.get("anchor"), path_id=label, field="anchor") for item in anchors)
    dx, dy = second[0] - first[0], second[1] - first[1]
    if dx == 0 and dy == 0:
        raise ExportValidationError(f"{label}: fold endpoints must differ")
    for point in anchors:
        for key in ("left_direction", "left", "right_direction", "right"):
            handle = point.get(key)
            if handle is None:
                continue
            hx, hy = _finite_pair(handle, path_id=label, field=key)
            if abs(dx * (hy - first[1]) - dy * (hx - first[0])) > 1e-6:
                raise ExportValidationError(f"{label}: PF_FOLD path must be straight")
    return list(first), list(second)


def export_from_dom(dom: dict[str, Any], *, source: Path, material: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize a *live Illustrator DOM result* into the portable export schema."""

    illustrator = dom.get("illustrator")
    if not isinstance(illustrator, dict) or illustrator.get("ok") is not True:
        raise ExportValidationError("Illustrator did not return a successful live DOM inspection")
    layers = illustrator.get("layer_names")
    if not isinstance(layers, list) or not {"PF_CUT", "PF_PRINT_FRONT", "PF_FOLD"}.issubset(layers):
        raise ExportValidationError("required layers PF_CUT, PF_PRINT_FRONT and PF_FOLD are missing")
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

    group_layers = illustrator.get("group_layers")
    group_entries = illustrator.get("group_entries")
    if not isinstance(group_layers, dict) or not isinstance(group_entries, list):
        raise ExportValidationError("Illustrator did not return group-to-layer membership data")
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: {"cut": [], "print": [], "fold": []})
    seen_groups: set[str] = set()
    for group in group_entries:
        if not isinstance(group, dict):
            continue
        name, layer = group.get("name"), group.get("layer")
        if not isinstance(name, str) or not isinstance(layer, str):
            continue
        if layer in {"PF_CUT", "PF_PRINT_FRONT", "PF_FOLD"} and name.startswith("PF_PART_"):
            marker = layer + ":" + name
            if marker in seen_groups:
                raise ExportValidationError(f"{layer}: duplicate part group {name}")
            seen_groups.add(marker)
            part_id = _part_id(name)
            if part_id is not None:
                grouped[part_id]
    for raw in raw_paths:
        if not isinstance(raw, dict):
            raise ExportValidationError("Illustrator returned a non-object path")
        parent = raw.get("parent")
        layer_name = raw.get("layer")
        if layer_name not in {"PF_CUT", "PF_PRINT_FRONT", "PF_FOLD"}:
            continue
        if layer_name == "PF_PRINT_FRONT":
            # The print deliverable is the layer-isolated PNG. Live text and
            # compound paths are valid artwork even when they have no closed
            # vector representation in this geometry IR.
            if not isinstance(parent, dict) or parent.get("type") == "Layer":
                raise ExportValidationError(f"{layer_name}: path {raw.get('name')!r} must be inside a PF_PART_<ID> group")
            if parent.get("type") != "GroupItem":
                ancestors = raw.get("ancestor_groups")
                if not isinstance(ancestors, list) or not any(
                    isinstance(group, dict)
                    and _part_id(group.get("name")) is not None
                    and group_layers.get(f"{layer_name}:{group.get('name')}") == layer_name
                    for group in ancestors
                ):
                    raise ExportValidationError(f"{layer_name}: path {raw.get('name')!r} must be inside a PF_PART_<ID> group")
                continue
        elif not isinstance(parent, dict) or parent.get("type") != "GroupItem":
            raise ExportValidationError(f"{layer_name}: path {raw.get('name')!r} must be directly inside a PF_PART_<ID> group")
        part_id = _part_id(parent.get("name"))
        if part_id is None:
            raise ExportValidationError(f"{layer_name}: path {raw.get('name')!r} is in a non-PF_PART group")
        group_name = parent["name"]
        kind_by_layer = {"PF_CUT": "cut", "PF_PRINT_FRONT": "print", "PF_FOLD": "fold"}
        kind = kind_by_layer.get(layer_name)
        if kind and group_layers.get(f"{layer_name}:{group_name}") == layer_name:
            grouped[part_id][kind].append(raw)
        else:
            raise ExportValidationError(f"{layer_name}: group {group_name} must be directly on its PF layer")

    exported_parts: list[dict[str, Any]] = []
    for part_id in sorted(grouped):
        part = grouped[part_id]
        if not part["cut"] and (part["print"] or part["fold"] or any(
            marker.endswith(":" + "PF_PART_" + part_id) for marker in seen_groups
        )):
            raise ExportValidationError(f"{part_id}: PF_PRINT_FRONT or PF_FOLD exists without PF_CUT geometry")
        cuts = [_normalize_path(raw, source_id=str(raw.get("id", f"cut.{part_id}.{index + 1}")), top_pt=top, left_pt=left)
                for index, raw in enumerate(part["cut"])]
        # AI may intentionally retain a non-printing cut path without a visible
        # stroke.  Geometry import needs the closed, unfilled contour; whether a
        # CAM-facing stroke is required belongs to a later output profile.
        if any(item["filled"] for item in cuts):
            raise ExportValidationError(f"{part_id}: PF_CUT contours must be unfilled")
        polygons = [_flatten_path(item) for item in cuts]
        containers = [[other_index for other_index, other_polygon in enumerate(polygons)
                       if other_index != index and _point_in_polygon(polygon[0], other_polygon)]
                      for index, polygon in enumerate(polygons)]
        outers = [item for index, item in enumerate(cuts) if not containers[index]]
        if len(outers) != 1:
            raise ExportValidationError(f"{part_id}: closed PF_CUT paths do not have one unambiguous outer contour")
        outer = outers[0]
        outer_index = cuts.index(outer)
        holes = [item for index, item in enumerate(cuts) if index != outer_index]
        if any(containers[index] != [outer_index] for index in range(len(cuts)) if index != outer_index):
            raise ExportValidationError(f"{part_id}: PF_CUT contour nesting is ambiguous; use one outer contour and non-nested holes")
        outer_bounds = _bbox([outer])
        if outer_bounds[2] <= outer_bounds[0] or outer_bounds[3] <= outer_bounds[1]:
            raise ExportValidationError(f"{part_id}: outer contour has no positive extent")
        fold_names: set[str] = set()
        folds = []
        outer_polygon = polygons[outer_index]
        for index, raw in enumerate(part["fold"]):
            label = raw.get("name") if isinstance(raw.get("name"), str) and raw["name"] else f"FOLD_{index + 1:02d}"
            if label in fold_names:
                raise ExportValidationError(f"{part_id}: duplicate PF_FOLD name {label!r}")
            fold_names.add(label)
            first, second = _is_straight_fold(raw, f"{part_id}/{label}")
            endpoints = [_point({"anchor": point, "left_direction": point, "right_direction": point}, path_id=f"{part_id}/{label}", top_pt=top, left_pt=left)["anchor_mm"] for point in (first, second)]
            folds.append({"id": label, "endpoints_mm": endpoints,
                          "boundary_relation": "not-evaluated-by-intake",
                          "status": "angle-and-direction-required-in-assembly-plan"})
        print_paths = [_normalize_path(raw, source_id=str(raw.get("id", f"print.{part_id}.{index + 1}")), top_pt=top, left_pt=left)
                       for index, raw in enumerate(part["print"]) if raw.get("closed") is True]
        exported_parts.append(
            {
                "id": part_id,
                "cut": {"outer": outer, "holes": holes},
                "dimensions_mm": [outer_bounds[2] - outer_bounds[0], outer_bounds[3] - outer_bounds[1]],
                "placement_bounds_mm": outer_bounds,
                "print_front": {"paths": print_paths, "bounds_mm": _bbox(print_paths) if print_paths else None},
                "folds": folds,
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
  var snapshot = documentSnapshot(documentRef);
  for (var pathIndex = 0; pathIndex < documentRef.pathItems.length; pathIndex++) {{
   var cursor = documentRef.pathItems[pathIndex]; var layerName = null; var ancestorGroups = [];
   while (cursor && cursor.parent) {{
    cursor = cursor.parent;
    if (cursor && cursor.typename === "GroupItem") ancestorGroups.push({{name: cursor.name || ""}});
    if (cursor && cursor.typename === "Layer") {{ layerName = cursor.name || ""; break; }}
   }}
   snapshot.paths[pathIndex].layer = layerName;
   snapshot.paths[pathIndex].ancestor_groups = ancestorGroups;
  }}
  return toJson({{ok: true, illustrator_version: app.version, snapshot: snapshot, groups: groups}});
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
    group_entries: list[dict[str, str]] = []
    if not isinstance(groups, list):
        raise RuntimeError("Illustrator did not return group memberships")
    for group in groups:
        if not isinstance(group, dict):
            continue
        name, parent = group.get("name"), group.get("parent")
        if isinstance(name, str) and isinstance(parent, dict) and parent.get("type") == "Layer" and isinstance(parent.get("name"), str):
            group_layers[f"{parent['name']}:{name}"] = parent["name"]
            group_entries.append({"name": name, "layer": parent["name"]})
    return {"status": "passed", "illustrator": {"ok": True, "illustrator_version": runtime.get("illustrator_version"), "layer_names": [item.get("name") for item in structure.get("layers", []) if isinstance(item, dict)], "artboards": structure.get("artboards"), "paths": snapshot.get("paths"), "group_layers": group_layers, "group_entries": group_entries}}


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
    from py_ai_illustrator.verification import _read_png_rgba

    width, height, pixels = _read_png_rgba(output.read_bytes())
    return {
        "visible_layer": "PF_PRINT_FRONT",
        "hidden_layers": hidden.split("|") if hidden else [],
        "path": str(output),
        "dpi": 144,
        "pixels": [width, height],
        "pixel_sha256": hashlib.sha256(pixels).hexdigest(),
    }


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
