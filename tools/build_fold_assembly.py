"""Build a rigid straight-fold assembly from a validated face-tree plan.

All cells are cut in the unfolded Blender world plane before any folding
transform is applied. This is essential for a chain: cutting a child after
its parent has moved makes the next source-space hinge meaningless.
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.fold_plan import load_plan
from tools.build_assembly_bundle import setup_scene
from tools.build_blender_panels import MM, front_material, make_panel, paper_material


def arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else [])


def fold_source(part, fold_id):
    return next(item for item in part.get("folds", []) if item["id"] == fold_id)


def line_world(endpoints):
    a, b = endpoints
    return Vector((a[0] * MM, -a[1] * MM, 0.0)), Vector((b[0] * MM, -b[1] * MM, 0.0))


def cut_half_flat(obj, endpoints, keeps_positive):
    """Intersect an object with one source-space half-plane while it is flat."""
    a, b = line_world(endpoints)
    direction = b - a
    direction.z = 0.0
    direction.normalize()
    normal = Vector((-direction.y, direction.x, 0.0))
    if not keeps_positive:
        normal.negate()
    size = 10000.0 * MM
    bpy.ops.mesh.primitive_cube_add(location=(a + b) / 2.0 + normal * size / 2.0)
    cutter = bpy.context.object
    cutter.name = "PF_FOLD_TEMP_CUTTER"
    cutter.dimensions = (size, size, 1.0)
    cutter.rotation_euler[2] = math.atan2(direction.y, direction.x)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    modifier = obj.modifiers.new("PF_FOLD_HALF", "BOOLEAN")
    modifier.operation = "INTERSECT"
    modifier.solver = "EXACT"
    modifier.object = cutter
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    obj.select_set(False)
    bpy.data.objects.remove(cutter, do_unlink=True)


def descendants(edges, root):
    children = {}
    for edge in edges:
        children.setdefault(edge["parent_face"], []).append(edge["child_face"])
    result, pending = set(), [root]
    while pending:
        face = pending.pop()
        if face not in result:
            result.add(face)
            pending.extend(children.get(face, ()))
    return result


def face_signatures(assembly):
    """Map every planned face to its side of every source fold."""
    faces = {assembly["root_face"]}
    for edge in assembly["folds"]:
        faces.update((edge["parent_face"], edge["child_face"]))
    signatures = {face: {} for face in faces}
    for edge in assembly["folds"]:
        moving = descendants(assembly["folds"], edge["child_face"])
        for face in faces:
            signatures[face][edge["fold_id"]] = edge["child_side"] if face in moving else -edge["child_side"]
    return signatures


def face_transforms(assembly, part):
    """Compute D_face from the already flat source-world coordinate system."""
    result = {assembly["root_face"]: Matrix.Identity(4)}
    unresolved = list(assembly["folds"])
    while unresolved:
        remaining = []
        for edge in unresolved:
            parent = result.get(edge["parent_face"])
            if parent is None:
                remaining.append(edge)
                continue
            source = fold_source(part, edge["fold_id"])
            pivot, endpoint = line_world(source["endpoints_mm"])
            axis = (endpoint - pivot).normalized()
            sign = 1.0 if edge["mountain_valley"] == "valley" else -1.0
            theta = sign * math.radians(180.0 - edge["target_dihedral_deg"])
            result[edge["child_face"]] = parent @ Matrix.Translation(pivot) @ Matrix.Rotation(theta, 4, axis) @ Matrix.Translation(-pivot)
        if len(remaining) == len(unresolved):
            raise RuntimeError("validated fold tree could not be transformed")
        unresolved = remaining
    return result


def assert_nonempty(obj, label):
    if obj.type != "MESH" or not obj.data.vertices or not obj.data.polygons:
        raise RuntimeError("empty face cell: " + label)


def main():
    args = arguments()
    root = Path(args.repo_root).resolve()
    plan = load_plan(args.plan, root)
    output = Path(args.output_dir).resolve()
    if output.exists():
        raise RuntimeError("output directory already exists; choose a new revision directory")
    from tools.panel_input import load_bundle
    bundle = load_bundle(root / plan["sources"]["export_json"], root / plan["sources"]["print_png"], allow_folds=True)
    parts = {part["id"]: part for part in bundle["parts"]}
    output.mkdir(parents=True)
    texture_dir = output / "textures"
    texture_dir.mkdir()
    shutil.copyfile(root / plan["sources"]["print_png"], texture_dir / "print-front.png")
    _, collection, _ = setup_scene()
    front = front_material(texture_dir / "print-front.png")
    bpy.data.images["PF_PRINT_FRONT_SOURCE"].filepath = "//textures/print-front.png"
    paper = paper_material()
    manifest = []
    for assembly in plan["assemblies"]:
        part = parts[assembly["part_id"]]
        flat_base = Matrix.Translation(Vector((part["bounds_mm"][0] * MM, -part["bounds_mm"][1] * MM, 0.0)))
        signatures = face_signatures(assembly)
        transforms = face_transforms(assembly, part)
        for face, signature in signatures.items():
            obj = make_panel(part, bundle["thickness_mm"], bundle["print_range_mm"], front, paper, collection)
            obj.name = "PF_FACE_" + assembly["id"] + "_" + face
            for edge in assembly["folds"]:
                cut_half_flat(obj, fold_source(part, edge["fold_id"])["endpoints_mm"], signature[edge["fold_id"]] > 0)
            assert_nonempty(obj, assembly["id"] + "/" + face)
            obj.matrix_world = transforms[face] @ flat_base
            obj["pf_face_id"] = face
            obj["pf_flat_base_matrix"] = [list(row) for row in flat_base]
        for edge in assembly["folds"]:
            source = fold_source(part, edge["fold_id"])
            manifest.append({"assembly": assembly["id"], "fold_id": edge["fold_id"], "parent": edge["parent_face"], "child": edge["child_face"], "dihedral_deg": edge["target_dihedral_deg"], "rotation_from_flat_deg": (1 if edge["mountain_valley"] == "valley" else -1) * (180 - edge["target_dihedral_deg"]), "endpoints_mm": source["endpoints_mm"]})
    bpy.ops.wm.save_as_mainfile(filepath=str(output / "assembly.blend"))
    (output / "fold-manifest.json").write_text(json.dumps({"model": "rigid-mid-plane-v2", "limitations": ["no bend radius", "no thickness collision guarantee", "no manufacturing guarantee"], "folds": manifest}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
