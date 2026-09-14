"""Blender-independent contract checks for numeric assembly placement.

The module intentionally describes only explicit input: source parts, instances,
world transforms and optional checks.  It does not infer a fixture type from an
ID, quantity, orientation, or name.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from tools.panel_input import InputError, load_bundle


SCHEMA_VERSION = "0.1"
WORLD = {
    "origin": "floor, back mid-plane, left inner face",
    "x_axis": "right",
    "y_axis": "back",
    "z_axis": "up",
    "rotation_mode": "XYZ extrinsic degrees",
}
TOP_LEVEL_FIELDS = {"schema_version", "status", "unit", "world", "sources", "instances", "checks"}
SOURCE_FIELDS = {"panels", "print_front"}
INSTANCE_FIELDS = {"id", "part_id", "translation_mm", "rotation_deg_xyz"}
CHECK_FIELDS = {"expected_checks", "expected_contacts"}
EXPECTED_CHECK_FIELDS = {"id", "instance_id", "kind", "face", "target_mm", "tolerance_mm"}
CONTACT_FIELDS = {"a", "a_face", "b", "b_face", "kind", "target_gap_mm", "tolerance_mm"}
FACES = {"min_x", "max_x", "min_y", "max_y", "min_z", "max_z"}


def _error(errors, message):
    errors.append(message)


def _finite_number(value, label, errors):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        _error(errors, f"{label} must be a finite number")
        return None
    return float(value)


def _vector(value, length, label, errors):
    if not isinstance(value, list) or len(value) != length:
        _error(errors, f"{label} must be an array of {length} finite numbers")
        return None
    result = [_finite_number(item, f"{label}[{index}]", errors) for index, item in enumerate(value)]
    return result if all(item is not None for item in result) else None


def _object(value, label, fields, errors, required=None):
    if not isinstance(value, dict):
        _error(errors, f"{label} must be an object")
        return None
    for key in value:
        if key not in fields:
            _error(errors, f"{label}.{key} is unknown")
    for key in (fields if required is None else required):
        if key not in value:
            _error(errors, f"{label}.{key} is required")
    return value


def _relative_existing_path(value, label, repository_root, errors):
    if not isinstance(value, str) or not value:
        _error(errors, f"{label} must be a non-empty repository-relative path")
        return None
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        _error(errors, f"{label} must not escape the repository: {value!r}")
        return None
    resolved = (repository_root / candidate).resolve()
    try:
        resolved.relative_to(repository_root)
    except ValueError:
        _error(errors, f"{label} must not escape the repository: {value!r}")
        return None
    if not resolved.is_file():
        _error(errors, f"{label} does not exist: {value}")
        return None
    return resolved


def rotation_matrix_xyz_degrees(rotation):
    """Return Rz * Ry * Rx for fixed-world-axis XYZ rotations in degrees."""
    x, y, z = (math.radians(value) for value in rotation)
    cx, sx, cy, sy, cz, sz = math.cos(x), math.sin(x), math.cos(y), math.sin(y), math.cos(z), math.sin(z)
    return (
        (cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx),
        (sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx),
        (-sy, cy * sx, cy * cx),
    )


def matrix_4x4(translation, rotation):
    matrix = rotation_matrix_xyz_degrees(rotation)
    return [
        [matrix[0][0], matrix[0][1], matrix[0][2], translation[0]],
        [matrix[1][0], matrix[1][1], matrix[1][2], translation[1]],
        [matrix[2][0], matrix[2][1], matrix[2][2], translation[2]],
        [0.0, 0.0, 0.0, 1.0],
    ]


def _transform(point, matrix):
    return tuple(sum(matrix[row][column] * point[column] for column in range(3)) + matrix[row][3] for row in range(3))


def _axis_aligned(matrix):
    rotation = [row[:3] for row in matrix[:3]]
    return all(sum(abs(value) > 1e-9 for value in row) == 1 and any(abs(abs(value) - 1.0) <= 1e-9 for value in row) for row in rotation) and all(sum(abs(rotation[row][column]) > 1e-9 for row in range(3)) == 1 for column in range(3))


def world_aabb(part, thickness_mm, matrix):
    """Transform the local placement box (left/top origin, +X/right, -Y/down)."""
    x0, y0, x1, y1 = part["bounds_mm"]
    width, height = x1 - x0, y1 - y0
    corners = [_transform((x, y, z), matrix) for x in (0.0, width) for y in (-height, 0.0) for z in (-thickness_mm / 2, thickness_mm / 2)]
    return {axis: (min(point[index] for point in corners), max(point[index] for point in corners)) for index, axis in enumerate(("x", "y", "z"))}


def _face_axis(face):
    return face[-1]


def _face_side(face):
    return face.split("_")[0]


def _validate_contact(contact, index, ids, errors):
    label = f"checks.expected_contacts[{index}]"
    if _object(contact, label, CONTACT_FIELDS, errors) is None:
        return
    for key in ("a", "b"):
        if not isinstance(contact.get(key), str) or contact[key] not in ids:
            _error(errors, f"{label}.{key} must reference an instance")
    if contact.get("a") == contact.get("b") and isinstance(contact.get("a"), str):
        _error(errors, f"{label} must use two different instances")
    a_face, b_face = contact.get("a_face"), contact.get("b_face")
    if a_face not in FACES or b_face not in FACES:
        _error(errors, f"{label} faces must be min_x, max_x, min_y, max_y, min_z, or max_z")
    elif _face_axis(a_face) != _face_axis(b_face) or _face_side(a_face) == _face_side(b_face):
        _error(errors, f"{label} faces must be opposite faces on one axis")
    if contact.get("kind") != "axis_aligned_face_contact":
        _error(errors, f"{label}.kind must be axis_aligned_face_contact")
    target_gap = _finite_number(contact.get("target_gap_mm"), f"{label}.target_gap_mm", errors)
    if target_gap is not None and target_gap < 0:
        _error(errors, f"{label}.target_gap_mm must be non-negative")
    tolerance = _finite_number(contact.get("tolerance_mm"), f"{label}.tolerance_mm", errors)
    if tolerance is not None and tolerance < 0:
        _error(errors, f"{label}.tolerance_mm must be non-negative")


def validate_placement(payload, repository_root):
    """Validate and resolve placement input; return normalized data or InputError."""
    root = Path(repository_root).resolve()
    errors = []
    if _object(payload, "input", TOP_LEVEL_FIELDS, errors) is None:
        raise InputError("; ".join(errors))
    if payload.get("schema_version") != SCHEMA_VERSION:
        _error(errors, f"schema_version must be {SCHEMA_VERSION!r}")
    if not isinstance(payload.get("status"), str) or not payload["status"]:
        _error(errors, "status must be a non-empty string")
    if payload.get("unit") != "mm":
        _error(errors, "unit must be 'mm'")
    world = _object(payload.get("world"), "world", set(WORLD), errors)
    if world is not None:
        for key, expected in WORLD.items():
            if world.get(key) != expected:
                _error(errors, f"world.{key} must be {expected!r}")
    sources = _object(payload.get("sources"), "sources", SOURCE_FIELDS, errors)
    panels = image = None
    if sources is not None:
        panels = _relative_existing_path(sources.get("panels"), "sources.panels", root, errors)
        image = _relative_existing_path(sources.get("print_front"), "sources.print_front", root, errors)
    bundle = None
    if panels and image:
        try:
            bundle = load_bundle(panels, image)
        except InputError as error:
            _error(errors, f"sources are not a valid panel bundle: {error}")
    instances = payload.get("instances")
    resolved = []
    ids = set()
    if not isinstance(instances, list) or not instances:
        _error(errors, "instances must be a non-empty array")
    else:
        part_ids = {part["id"] for part in bundle["parts"]} if bundle else set()
        for index, instance in enumerate(instances):
            label = f"instances[{index}]"
            if _object(instance, label, INSTANCE_FIELDS, errors) is None:
                continue
            instance_id = instance.get("id")
            if not isinstance(instance_id, str) or not instance_id:
                _error(errors, f"{label}.id must be a non-empty string")
            elif instance_id in ids:
                _error(errors, f"{label}.id is duplicated: {instance_id}")
            else:
                ids.add(instance_id)
            part_id = instance.get("part_id")
            if not isinstance(part_id, str) or part_id not in part_ids:
                _error(errors, f"{label}.part_id is unknown: {part_id!r}")
            translation = _vector(instance.get("translation_mm"), 3, f"{label}.translation_mm", errors)
            rotation = _vector(instance.get("rotation_deg_xyz"), 3, f"{label}.rotation_deg_xyz", errors)
            if isinstance(instance_id, str) and instance_id and part_id in part_ids and translation and rotation:
                part = next(part for part in bundle["parts"] if part["id"] == part_id)
                matrix = matrix_4x4(translation, rotation)
                resolved.append({"id": instance_id, "part_id": part_id, "translation_mm": translation, "rotation_deg_xyz": rotation, "matrix_mm": matrix, "world_aabb_mm": world_aabb(part, bundle["thickness_mm"], matrix)})
    checks = _object(payload.get("checks", {}), "checks", CHECK_FIELDS, errors, required=[])
    if checks is not None:
        expected_checks = checks.get("expected_checks", [])
        if not isinstance(expected_checks, list):
            _error(errors, "checks.expected_checks must be an array")
        else:
            check_ids = set()
            for index, check in enumerate(expected_checks):
                label = f"checks.expected_checks[{index}]"
                if _object(check, label, EXPECTED_CHECK_FIELDS, errors) is None:
                    continue
                check_id = check.get("id")
                if not isinstance(check_id, str) or not check_id or check_id in check_ids:
                    _error(errors, f"{label}.id must be a unique non-empty string")
                else:
                    check_ids.add(check_id)
                if not isinstance(check.get("instance_id"), str) or check["instance_id"] not in ids:
                    _error(errors, f"{label}.instance_id must reference an instance")
                if check.get("kind") != "world_aabb_face":
                    _error(errors, f"{label}.kind must be world_aabb_face")
                if check.get("face") not in FACES:
                    _error(errors, f"{label}.face must be an AABB face")
                _finite_number(check.get("target_mm"), f"{label}.target_mm", errors)
                tolerance = _finite_number(check.get("tolerance_mm"), f"{label}.tolerance_mm", errors)
                if tolerance is not None and tolerance < 0:
                    _error(errors, f"{label}.tolerance_mm must be non-negative")
        contacts = checks.get("expected_contacts", [])
        if not isinstance(contacts, list):
            _error(errors, "checks.expected_contacts must be an array")
        else:
            pairs = set()
            for index, contact in enumerate(contacts):
                _validate_contact(contact, index, ids, errors)
                if isinstance(contact, dict) and contact.get("a") in ids and contact.get("b") in ids:
                    pair = tuple(sorted((contact["a"], contact["b"])))
                    if pair in pairs:
                        _error(errors, f"checks.expected_contacts[{index}] duplicates pair {pair[0]!r}, {pair[1]!r}")
                    pairs.add(pair)
    if errors:
        raise InputError("; ".join(errors))
    return {"schema_version": SCHEMA_VERSION, "sources": {"panels": str(panels.relative_to(root)), "print_front": str(image.relative_to(root))}, "thickness_mm": bundle["thickness_mm"], "instances": resolved, "checks": checks or {}}


def evaluate_checks(resolved):
    """Evaluate optional AABB checks.  Contacts with rotated AABBs are diagnostic-only."""
    errors, report = [], {"expected_checks": [], "expected_contacts": []}
    instances = {item["id"]: item for item in resolved["instances"]}
    for check in resolved["checks"].get("expected_checks", []):
        aabb = instances[check["instance_id"]]["world_aabb_mm"]
        actual = aabb[_face_axis(check["face"])][0 if _face_side(check["face"]) == "min" else 1]
        passed = abs(actual - check["target_mm"]) <= check["tolerance_mm"]
        report["expected_checks"].append({"id": check["id"], "actual_mm": actual, "passed": passed})
        if not passed:
            errors.append(f"expected check {check['id']!r}: expected {check['target_mm']} mm, got {actual} mm")
    for contact in resolved["checks"].get("expected_contacts", []):
        first, second = instances[contact["a"]], instances[contact["b"]]
        axis = _face_axis(contact["a_face"])
        if not _axis_aligned(first["matrix_mm"]) or not _axis_aligned(second["matrix_mm"]):
            report["expected_contacts"].append({"a": contact["a"], "b": contact["b"], "applicable": False, "passed": False})
            errors.append(f"expected contact {contact['a']!r}/{contact['b']!r} is not applicable to non-axis-aligned rotation")
            continue
        a_value = first["world_aabb_mm"][axis][0 if _face_side(contact["a_face"]) == "min" else 1]
        b_value = second["world_aabb_mm"][axis][0 if _face_side(contact["b_face"]) == "min" else 1]
        # A positive value is separation and a negative value is penetration.
        # The sign is defined by the two facing AABB sides, not contact ordering.
        gap = a_value - b_value if _face_side(contact["a_face"]) == "min" else b_value - a_value
        other_axes = [candidate for candidate in "xyz" if candidate != axis]
        overlaps = all(min(first["world_aabb_mm"][candidate][1], second["world_aabb_mm"][candidate][1]) - max(first["world_aabb_mm"][candidate][0], second["world_aabb_mm"][candidate][0]) > 0 for candidate in other_axes)
        passed = overlaps and abs(gap - contact["target_gap_mm"]) <= contact["tolerance_mm"]
        report["expected_contacts"].append({"a": contact["a"], "b": contact["b"], "gap_mm": gap, "overlaps_other_axes": overlaps, "passed": passed})
        if not passed:
            errors.append(f"expected contact {contact['a']!r}/{contact['b']!r} is not satisfied")
    if errors:
        raise InputError("; ".join(errors))
    return report


def load_placement(path, repository_root):
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise InputError(f"invalid placement JSON: {error}") from error
    return validate_placement(payload, repository_root)
