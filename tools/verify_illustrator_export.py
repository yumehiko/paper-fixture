#!/usr/bin/env python3
"""Numerically verify a live-DOM paper-fixture export and create a 2D overlay."""

from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path
from typing import Any

from export_illustrator import MM_PER_PT, _note_id
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


def _cut_red_pixel_count(path: Path) -> int:
    _width, _height, pixels = _read_png_rgba(path.read_bytes())
    return sum(1 for index in range(0, len(pixels), 4) if pixels[index] > 240 and pixels[index + 1] < 40 and pixels[index + 2] < 40 and pixels[index + 3] > 0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export_dir", type=Path)
    args = parser.parse_args(argv)
    root = args.export_dir
    package = json.loads((root / "export.json").read_text(encoding="utf-8"))
    evidence = json.loads((root / "evidence.json").read_text(encoding="utf-8"))
    numeric = _verify_live_dom(package, evidence)
    artboard_png, print_png = root / "artboard.preview.png", root / "print-front.png"
    width, height = _png_size(print_png)
    _write_overlay(package, artboard_png, root / "geometry-overlay.svg")
    print_evidence = evidence.get("print_front_png", {})
    print_only = {"png": print_png.name, "pixels": [width, height], "range_mm": package["print"]["range_mm"], "formula": package["print"]["pixel_mapping"], "visible_layer": print_evidence.get("visible_layer"), "hidden_layers": print_evidence.get("hidden_layers"), "cut_red_pixels": _cut_red_pixel_count(print_png), "passed": print_evidence.get("visible_layer") == "PF_PRINT_FRONT" and _cut_red_pixel_count(print_png) == 0}
    result = {"profile": "paper-fixture-export-verification-v1", "numeric_live_dom_roundtrip": numeric, "print_pixel_mapping": print_only, "2d_overlay": {"path": "geometry-overlay.svg", "source": artboard_png.name, "semantics": "magenta outer, yellow holes, cyan front-print paths"}, "status": "passed" if numeric["passed"] and print_only["passed"] else "failed"}
    (root / "validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
