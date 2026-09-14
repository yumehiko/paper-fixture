"""Input validation and Bézier helpers for the Blender panel prototype.

This module deliberately has no Blender dependency so the input contract can be
tested with the repository's normal Python interpreter.
"""

from __future__ import annotations

import json
import math
from pathlib import Path


class InputError(ValueError):
    """Raised when an Illustrator-export bundle cannot safely be modelled."""


REQUIRED_SCHEMA = "paper-fixture-illustrator-export-v1"


def _number_pair(value, label):
    if not isinstance(value, list) or len(value) != 2 or not all(
        isinstance(item, (int, float)) and math.isfinite(item) for item in value
    ):
        raise InputError(f"{label} must be two finite numbers")
    return (float(value[0]), float(value[1]))


def signed_area(points):
    """Return the signed area of anchor points in their supplied coordinate plane."""
    return sum(
        point[0] * points[(index + 1) % len(points)][1]
        - points[(index + 1) % len(points)][0] * point[1]
        for index, point in enumerate(points)
    ) / 2.0


def validate_path(path, label):
    if not isinstance(path, dict) or path.get("closed") is not True:
        raise InputError(f"{label} must be a closed path")
    points = path.get("points")
    if not isinstance(points, list) or len(points) < 3:
        raise InputError(f"{label} needs at least three points")
    normalized = []
    for index, point in enumerate(points):
        if not isinstance(point, dict):
            raise InputError(f"{label}.points[{index}] must be an object")
        normalized.append(
            {
                "anchor_mm": _number_pair(point.get("anchor_mm"), f"{label}.points[{index}].anchor_mm"),
                "in_handle_mm": _number_pair(point.get("in_handle_mm"), f"{label}.points[{index}].in_handle_mm"),
                "out_handle_mm": _number_pair(point.get("out_handle_mm"), f"{label}.points[{index}].out_handle_mm"),
            }
        )
    anchors = [point["anchor_mm"] for point in normalized]
    if abs(signed_area(anchors)) < 1e-8:
        raise InputError(f"{label} has zero signed area")
    return normalized


def load_bundle(export_json, print_png):
    """Validate and return an export bundle without changing its source files."""
    export_path = Path(export_json)
    image_path = Path(print_png)
    if not export_path.is_file():
        raise InputError(f"export.json does not exist: {export_path}")
    if not image_path.is_file() or image_path.stat().st_size == 0:
        raise InputError(f"print-front.png is missing or empty: {image_path}")
    try:
        payload = json.loads(export_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise InputError(f"invalid JSON: {error}") from error
    if payload.get("schema") != REQUIRED_SCHEMA:
        raise InputError(f"unsupported schema: {payload.get('schema')!r}")
    coordinate_system = payload.get("coordinate_system", {})
    if (coordinate_system.get("unit"), coordinate_system.get("origin"), coordinate_system.get("x_axis"), coordinate_system.get("y_axis")) != (
        "mm", "artboard upper-left", "right", "down"
    ):
        raise InputError("only mm / artboard upper-left / +X right / +Y down is supported")
    thickness = payload.get("material", {}).get("thickness_mm")
    if not isinstance(thickness, (int, float)) or not math.isfinite(thickness) or thickness <= 0:
        raise InputError("material.thickness_mm must be a positive finite number")
    print_range = _number_quad(payload.get("print", {}).get("range_mm"), "print.range_mm")
    if print_range[2] <= print_range[0] or print_range[3] <= print_range[1]:
        raise InputError("print.range_mm must have positive width and height")
    parts = payload.get("parts")
    if not isinstance(parts, list) or not parts:
        raise InputError("parts must be a non-empty list")
    seen_ids = set()
    normalized_parts = []
    for index, part in enumerate(parts):
        label = f"parts[{index}]"
        part_id = part.get("id") if isinstance(part, dict) else None
        if not isinstance(part_id, str) or not part_id or part_id in seen_ids:
            raise InputError(f"{label}.id must be a unique non-empty string")
        seen_ids.add(part_id)
        bounds = _number_quad(part.get("placement_bounds_mm"), f"{label}.placement_bounds_mm")
        if bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
            raise InputError(f"{label}.placement_bounds_mm must have positive width and height")
        cut = part.get("cut", {})
        outer = validate_path(cut.get("outer"), f"{label}.cut.outer")
        holes = [validate_path(hole, f"{label}.cut.holes[{hole_index}]") for hole_index, hole in enumerate(cut.get("holes", []))]
        normalized_parts.append({"id": part_id, "bounds_mm": bounds, "outer": outer, "holes": holes})
    return {"payload": payload, "thickness_mm": float(thickness), "print_range_mm": print_range, "parts": normalized_parts}


def _number_quad(value, label):
    if not isinstance(value, list) or len(value) != 4 or not all(isinstance(item, (int, float)) and math.isfinite(item) for item in value):
        raise InputError(f"{label} must be four finite numbers")
    return tuple(float(item) for item in value)
