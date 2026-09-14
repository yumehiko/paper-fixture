"""Re-open an assembly bundle and verify its editable, relocated contents.

This script deliberately accepts only the bundle directory.  It can therefore
be run after the bundle has moved away from the source checkout.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector


MM = 0.001
TOLERANCE_MM = 5e-4


def arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--report", required=True)
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fail(message):
    raise RuntimeError(message)


def close(actual, expected, label):
    if abs(actual - expected) > TOLERANCE_MM:
        fail(f"{label}: expected {expected} mm, got {actual} mm")


def matrix_mm(object_):
    return [[object_.matrix_world[row][column] / MM if column == 3 and row < 3 else object_.matrix_world[row][column]
             for column in range(4)] for row in range(4)]


def expected_aabb(bounds, thickness, matrix):
    width, height = bounds[2] - bounds[0], bounds[3] - bounds[1]
    points = []
    for x in (0.0, width):
        for y in (-height, 0.0):
            for z in (-thickness / 2, thickness / 2):
                points.append([sum(matrix[row][column] * (x, y, z)[column] for column in range(3)) + matrix[row][3]
                               for row in range(3)])
    return {axis: [min(point[index] for point in points), max(point[index] for point in points)]
            for index, axis in enumerate("xyz")}


def mesh_aabb(object_):
    points = [object_.matrix_world @ vertex.co for vertex in object_.data.vertices]
    return {axis: [min(point[index] for point in points) / MM, max(point[index] for point in points) / MM]
            for index, axis in enumerate("xyz")}


def normalized(vector):
    result = Vector(vector)
    result.normalize()
    return result


def front_image(material):
    nodes = [node for node in material.node_tree.nodes if node.bl_idname == "ShaderNodeTexImage"]
    return nodes[0].image if len(nodes) == 1 else None


def hole_is_open(object_, hole, bounds):
    anchors = [point["anchor_mm"] for point in hole]
    x = sum(point[0] for point in anchors) / len(anchors)
    y = sum(point[1] for point in anchors) / len(anchors)
    origin = Vector(((x - bounds[0]) * MM, -(y - bounds[1]) * MM, 0.1))
    hit, _, _, _ = object_.ray_cast(origin, Vector((0, 0, -1)))
    return not hit


def verify_instance(item, image_path):
    instance_id = item["id"]
    object_ = bpy.data.objects.get("PF_INSTANCE_" + instance_id)
    if object_ is None or object_.type != "MESH":
        fail("missing editable mesh instance: " + instance_id)
    if tuple(object_.scale) != (1, 1, 1):
        fail("instance scale is not one: " + instance_id)
    if object_.data.users != 1:
        fail("instance mesh data is shared: " + instance_id)
    if object_.get("pf_instance_id") != instance_id or object_.get("pf_part_id") != item["part_id"]:
        fail("instance/part mapping mismatch: " + instance_id)
    stored_matrix = json.loads(object_["pf_resolved_matrix_mm"])
    actual_matrix = matrix_mm(object_)
    for row in range(4):
        for column in range(4):
            close(actual_matrix[row][column], item["matrix_mm"][row][column], f"transform {instance_id}[{row},{column}]")
            close(stored_matrix[row][column], item["matrix_mm"][row][column], f"stored transform {instance_id}[{row},{column}]")
    bounds = list(item["source_bounds_mm"])
    thickness = float(item["thickness_mm"])
    if list(object_.get("pf_source_bounds_mm", [])) != bounds or float(object_.get("pf_thickness_mm", -1)) != thickness:
        fail("mesh source geometry properties do not match manifest: " + instance_id)
    expected_box, actual_box = expected_aabb(bounds, thickness, item["matrix_mm"]), mesh_aabb(object_)
    for axis in "xyz":
        for side in range(2):
            close(actual_box[axis][side], expected_box[axis][side], f"world AABB {instance_id}.{axis}[{side}]")
    mesh = object_.data
    checked = bmesh.new(); checked.from_mesh(mesh)
    closed = all(len(edge.link_faces) == 2 for edge in checked.edges); checked.free()
    if not closed:
        fail("mesh is not closed manifold: " + instance_id)
    holes = item["source_holes"]
    if json.loads(object_.get("pf_source_holes", "null")) != holes:
        fail("mesh source hole properties do not match manifest: " + instance_id)
    holes_open = [hole_is_open(object_, hole, bounds) for hole in holes]
    if not all(holes_open):
        fail("cut hole is not open: " + instance_id)
    local_z = [vertex.co.z / MM for vertex in mesh.vertices]
    close(max(local_z) - min(local_z), thickness, "thickness " + instance_id)
    local_x, local_y = [vertex.co.x / MM for vertex in mesh.vertices], [vertex.co.y / MM for vertex in mesh.vertices]
    close(max(local_x) - min(local_x), bounds[2] - bounds[0], "width " + instance_id)
    close(max(local_y) - min(local_y), bounds[3] - bounds[1], "height " + instance_id)
    front = [polygon for polygon in mesh.polygons if polygon.normal.z > .9]
    back = [polygon for polygon in mesh.polygons if polygon.normal.z < -.9]
    edge = [polygon for polygon in mesh.polygons if abs(polygon.normal.z) < .1]
    if not front or not back or not edge or any(p.material_index != 0 for p in front) or any(p.material_index != 1 for p in back + edge):
        fail("front/back material assignment failed: " + instance_id)
    material = mesh.materials[0] if mesh.materials else None
    image = front_image(material) if material and material.name == "PF_PRINT_FRONT" else None
    if image is None or image.filepath != "//textures/print-front.png" or Path(bpy.path.abspath(image.filepath)).resolve() != image_path:
        fail("front image is not the bundle-relative texture: " + instance_id)
    if "front_normal_world" not in item:
        fail("manifest front normal is missing: " + instance_id)
    expected_normal = normalized(item["front_normal_world"])
    transform_normal = normalized([item["matrix_mm"][row][2] for row in range(3)])
    if expected_normal.dot(transform_normal) < .999999:
        fail("manifest front normal does not match placement transform: " + instance_id)
    for polygon in front:
        if normalized(object_.matrix_world.to_3x3() @ polygon.normal).dot(expected_normal) < .999999:
            fail("front normal does not match placement transform: " + instance_id)
    uv = mesh.uv_layers.get("PF_PRINT_UV")
    print_range = list(item["print_range_mm"])
    if list(object_.get("pf_print_range_mm", [])) != print_range:
        fail("mesh print range property does not match manifest: " + instance_id)
    if uv is None:
        fail("front UV layer missing: " + instance_id)
    for polygon in front:
        for loop_index in polygon.loop_indices:
            vertex = mesh.vertices[mesh.loops[loop_index].vertex_index]
            global_x, global_y = vertex.co.x / MM + bounds[0], -vertex.co.y / MM + bounds[1]
            expected = ((global_x - print_range[0]) / (print_range[2] - print_range[0]), 1 - (global_y - print_range[1]) / (print_range[3] - print_range[1]))
            actual = uv.data[loop_index].uv
            if abs(actual.x - expected[0]) > 1e-6 or abs(actual.y - expected[1]) > 1e-6:
                fail("front UV mapping failed: " + instance_id)
    return {"id": instance_id, "part_id": item["part_id"], "mesh": mesh.name, "closed_manifold": closed,
            "independent_mesh": True, "scale_one": True, "world_aabb_mm": actual_box,
            "expected_world_aabb_mm": expected_box, "front_normal_world": list(expected_normal), "holes_open": holes_open}


def _face_value(aabb, face):
    return aabb[face[-1]][0 if face.startswith("min_") else 1]


def _axis_aligned(matrix):
    rotation = [row[:3] for row in matrix[:3]]
    return all(sum(abs(value) > 1e-9 for value in row) == 1 for row in rotation) and all(
        sum(abs(rotation[row][column]) > 1e-9 for row in range(3)) == 1 for column in range(3))


def verify_placement_checks(checks, findings, manifest_instances):
    """Re-evaluate placement assertions from reopened mesh world bounds."""
    actual = {item["id"]: item["world_aabb_mm"] for item in findings}
    matrices = {item["id"]: item["matrix_mm"] for item in manifest_instances}
    report = {"expected_checks": [], "expected_contacts": []}
    for check in checks.get("expected_checks", []):
        value = _face_value(actual[check["instance_id"]], check["face"])
        passed = abs(value - check["target_mm"]) <= check["tolerance_mm"]
        report["expected_checks"].append({"id": check["id"], "actual_mm": value, "passed": passed})
        if not passed:
            fail(f"reopened placement check {check['id']!r}: expected {check['target_mm']} mm, got {value} mm")
    for contact in checks.get("expected_contacts", []):
        first, second = contact["a"], contact["b"]
        if not _axis_aligned(matrices[first]) or not _axis_aligned(matrices[second]):
            fail(f"reopened contact {first!r}/{second!r} is not applicable to non-axis-aligned rotation")
        axis = contact["a_face"][-1]
        a_value, b_value = _face_value(actual[first], contact["a_face"]), _face_value(actual[second], contact["b_face"])
        gap = a_value - b_value if contact["a_face"].startswith("min_") else b_value - a_value
        overlap = all(min(actual[first][other][1], actual[second][other][1]) - max(actual[first][other][0], actual[second][other][0]) > 0
                      for other in "xyz" if other != axis)
        passed = overlap and abs(gap - contact["target_gap_mm"]) <= contact["tolerance_mm"]
        report["expected_contacts"].append({"a": first, "b": second, "gap_mm": gap, "overlaps_other_axes": overlap, "passed": passed})
        if not passed:
            fail(f"reopened contact {first!r}/{second!r} is not satisfied")
    return report


def main():
    args = arguments()
    bundle = Path(args.bundle).resolve()
    report_path = Path(args.report).resolve()
    if report_path.is_relative_to(bundle):
        fail("--report must be outside --bundle so it cannot change bundle provenance")
    manifest = json.loads((bundle / "build-manifest.json").read_text(encoding="utf-8"))
    if manifest.get("manifest_version") != 1 or not isinstance(manifest.get("instances"), list):
        fail("unsupported or invalid build manifest")
    output_hashes = manifest.get("output_hashes")
    if not isinstance(output_hashes, dict):
        fail("bundle provenance verification: output_hashes is missing")
    for name, expected_hash in output_hashes.items():
        candidate = bundle / name
        if not candidate.is_file() or sha(candidate) != expected_hash:
            category = "preview verification" if name.startswith("preview-") else "bundle provenance verification"
            fail(f"{category}: missing or changed output {name}")
    image_path = (bundle / "textures/print-front.png").resolve()
    if not image_path.is_file():
        fail("bundle texture is missing")
    expected_texture = manifest.get("output_hashes", {}).get("textures/print-front.png")
    texture_hash = sha(image_path)
    if texture_hash != expected_texture:
        fail("bundle texture hash does not match manifest")
    source_texture = manifest.get("input_hashes", {}).get("print_front", {}).get("sha256")
    if not isinstance(source_texture, str) or texture_hash != source_texture:
        fail("bundle texture does not match source print_front input hash")
    findings = [verify_instance(item, image_path) for item in manifest["instances"]]
    placement_checks = verify_placement_checks(manifest.get("checks", {}), findings, manifest["instances"])
    report = {"reopened": True, "bundle": str(bundle), "instance_count": len(findings), "instances": findings,
              "texture_sha256": texture_hash, "texture_hash_matches_manifest": True,
              "source_input_hashes": manifest.get("input_hashes", {}), "placement_checks": placement_checks}
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
