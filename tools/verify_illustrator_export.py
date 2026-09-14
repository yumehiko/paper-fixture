#!/usr/bin/env python3
"""Numerically verify a live-DOM paper-fixture export and create a 2D overlay."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import tempfile
from pathlib import Path
from typing import Any

from export_illustrator import MM_PER_PT, _note_id, export_print_front_png
from py_ai_illustrator.verification import _read_png_rgba


def _png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()[:24]
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise ValueError(f"not a PNG: {path}")
    return struct.unpack(">II", data[16:24])


def _paths(package: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for part in package["parts"]:
        result.append(part["cut"]["outer"])
        result.extend(part["cut"]["holes"])
        result.extend(part["print_front"]["paths"])
    return result


def _verify_live_dom(package: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    live = evidence["dom"]["illustrator"]
    artboard = live["artboards"][0]["rect"]
    left, top = float(artboard[0]), float(artboard[1])
    source = {_note_id(path): path for path in live["paths"]}
    exported = {path["source_id"]: path for path in _paths(package)}
    missing, extra = sorted(set(source) - set(exported)), sorted(set(exported) - set(source))
    errors: list[float] = []
    for identifier in sorted(set(source) & set(exported)):
        original, normalized = source[identifier], exported[identifier]
        for key, original_key in (("anchor_mm", "anchor"), ("in_handle_mm", "left"), ("out_handle_mm", "right")):
            for original_point, normalized_point in zip(original["anchors"], normalized["points"], strict=True):
                expected = [(float(original_point[original_key][0]) - left) * MM_PER_PT, (top - float(original_point[original_key][1])) * MM_PER_PT]
                errors.extend(abs(expected[index] - normalized_point[key][index]) for index in range(2))
    maximum = max(errors, default=0.0)
    return {"source_path_ids": len(source), "exported_path_ids": len(exported), "missing_ids": missing, "extra_ids": extra, "max_coordinate_error_mm": maximum, "tolerance_mm": 0.000001, "passed": not missing and not extra and maximum <= 0.000001}


def _svg_path(path: dict[str, Any], *, x_scale: float, y_scale: float) -> str:
    points = path["points"]
    first = points[0]["anchor_mm"]
    commands = [f"M {first[0] * x_scale:.6f} {first[1] * y_scale:.6f}"]
    for index in range(len(points)):
        previous, current = points[index - 1], points[index]
        out_handle, in_handle, anchor = previous["out_handle_mm"], current["in_handle_mm"], current["anchor_mm"]
        commands.append(f"C {out_handle[0] * x_scale:.6f} {out_handle[1] * y_scale:.6f} {in_handle[0] * x_scale:.6f} {in_handle[1] * y_scale:.6f} {anchor[0] * x_scale:.6f} {anchor[1] * y_scale:.6f}")
    return " ".join(commands) + " Z"


def _write_overlay(package: dict[str, Any], png: Path, output: Path) -> None:
    width, height = _png_size(png)
    artboard = package["coordinate_system"]["artboard_bounds_mm"]
    x_scale, y_scale = width / artboard[2], height / artboard[3]
    elements = []
    for part in package["parts"]:
        elements.append(f'<path d="{_svg_path(part["cut"]["outer"], x_scale=x_scale, y_scale=y_scale)}" class="cut"/>')
        elements.extend(f'<path d="{_svg_path(path, x_scale=x_scale, y_scale=y_scale)}" class="hole"/>' for path in part["cut"]["holes"])
        elements.extend(f'<path d="{_svg_path(path, x_scale=x_scale, y_scale=y_scale)}" class="print"/>' for path in part["print_front"]["paths"])
    output.write_text("\n".join([f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">', '<image href="artboard.preview.png" width="100%" height="100%"/>', '<style>.cut{fill:none;stroke:#f0f;stroke-width:1.5}.hole{fill:none;stroke:#ff0;stroke-width:1.5}.print{fill:none;stroke:#0ff;stroke-width:.75}</style>', *elements, '</svg>', '']), encoding="utf-8")


def _png_pixels(path: Path) -> tuple[int, int, bytes]:
    return _read_png_rgba(path.read_bytes())


def _verify_print_isolation(
    evidence: dict[str, Any],
    print_png: Path,
    reference_png: Path | None,
) -> dict[str, Any]:
    """Check a print PNG against an independent PF_PRINT_FRONT-only export.

    Layer visibility alone is only provenance.  The reference raster is created
    from the native source in a fresh Illustrator document, so it also detects
    a PF_CUT, annotation, or fold layer accidentally included in the delivered
    PNG without treating any print colour as reserved.
    """
    print_evidence = evidence.get("print_front_png")
    illustrator = evidence.get("dom", {}).get("illustrator", {})
    layers = illustrator.get("layer_names") if isinstance(illustrator, dict) else None
    if not isinstance(print_evidence, dict) or not isinstance(layers, list) or not all(isinstance(layer, str) for layer in layers):
        return {"passed": False, "error": "print isolation evidence is incomplete"}
    expected_hidden = sorted(layer for layer in layers if layer != "PF_PRINT_FRONT")
    reported_hidden = print_evidence.get("hidden_layers")
    provenance_ok = (
        "PF_PRINT_FRONT" in layers
        and print_evidence.get("visible_layer") == "PF_PRINT_FRONT"
        and isinstance(reported_hidden, list)
        and sorted(reported_hidden) == expected_hidden
    )
    width, height, pixels = _png_pixels(print_png)
    pixel_sha256 = hashlib.sha256(pixels).hexdigest()
    recorded_hash_ok = print_evidence.get("pixel_sha256") == pixel_sha256
    result: dict[str, Any] = {
        "visible_layer": print_evidence.get("visible_layer"),
        "hidden_layers": reported_hidden,
        "expected_hidden_layers": expected_hidden,
        "pixels": [width, height],
        "pixel_sha256": pixel_sha256,
        "recorded_pixel_sha256": print_evidence.get("pixel_sha256"),
        "layer_provenance_passed": provenance_ok,
        "recorded_hash_passed": recorded_hash_ok,
    }
    if reference_png is None:
        result.update({"fresh_print_only_reexport": "unavailable", "passed": False})
        return result
    reference_width, reference_height, reference_pixels = _png_pixels(reference_png)
    reference_hash = hashlib.sha256(reference_pixels).hexdigest()
    reference_ok = (width, height, pixels) == (reference_width, reference_height, reference_pixels)
    result.update({
        "fresh_print_only_reexport": "matched" if reference_ok else "mismatched",
        "reference_pixels": [reference_width, reference_height],
        "reference_pixel_sha256": reference_hash,
        "passed": provenance_ok and recorded_hash_ok and reference_ok,
    })
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export_dir", type=Path)
    parser.add_argument("--source", type=Path, help="native AI source; defaults to export.json source.path")
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args(argv)
    root = args.export_dir
    package = json.loads((root / "export.json").read_text(encoding="utf-8"))
    evidence = json.loads((root / "evidence.json").read_text(encoding="utf-8"))
    numeric = _verify_live_dom(package, evidence)
    artboard_png, print_png = root / "artboard.preview.png", root / "print-front.png"
    width, height = _png_size(print_png)
    _write_overlay(package, artboard_png, root / "geometry-overlay.svg")
    source_value = args.source or Path(package.get("source", {}).get("path", ""))
    reference_png: Path | None = None
    reference_error: str | None = None
    reference_directory: tempfile.TemporaryDirectory[str] | None = None
    if source_value.is_file():
        try:
            reference_directory = tempfile.TemporaryDirectory(prefix="paper-fixture-print-verify-")
            reference_png = Path(reference_directory.name) / "print-front.reference.png"
            export_print_front_png(source_value, reference_png, timeout=args.timeout)
        except RuntimeError as error:
            reference_error = str(error)
    else:
        reference_error = f"native AI source is unavailable: {source_value}"
    print_only = {"png": print_png.name, "range_mm": package["print"]["range_mm"], "formula": package["print"]["pixel_mapping"], "source": str(source_value), **_verify_print_isolation(evidence, print_png, reference_png)}
    if reference_error:
        print_only["reference_error"] = reference_error
    if reference_directory is not None:
        reference_directory.cleanup()
    result = {"profile": "paper-fixture-export-verification-v1", "numeric_live_dom_roundtrip": numeric, "print_pixel_mapping": print_only, "2d_overlay": {"path": "geometry-overlay.svg", "source": artboard_png.name, "semantics": "magenta outer, yellow holes, cyan front-print paths"}, "status": "passed" if numeric["passed"] and print_only["passed"] else "failed"}
    (root / "validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
