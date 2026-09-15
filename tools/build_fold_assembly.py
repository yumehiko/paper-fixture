"""Build and separately verify a protected rigid straight-fold bundle."""
from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
import tempfile
import json as _json
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.assembly_bundle_output import assert_replaceable, create_staging, publish_staging, resolve_output_boundary, sha256
from tools.fold_plan import load_plan
from tools.build_assembly_bundle import setup_scene
from tools.build_blender_panels import MM, front_material, make_panel, paper_material


OUTPUT_NAMES = {"assembly.blend", "fold-manifest.json", "textures/print-front.png", "verification.json"}


def arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--force", action="store_true")
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
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.remove_doubles(threshold=1e-7)
    bpy.ops.mesh.fill_holes(sides=0)
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode="OBJECT")
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
    faces = {assembly["root_face"]}
    for edge in assembly["folds"]:
        faces.update((edge["parent_face"], edge["child_face"]))
    signatures = {face: {} for face in faces}
    for edge in assembly["folds"]:
        moving = descendants(assembly["folds"], edge["child_face"])
        for face in faces:
            signatures[face][edge["fold_id"]] = edge["child_side"] if face in moving else -edge["child_side"]
    return signatures


def matrix_from_mm(values):
    result = Matrix(values)
    for row in range(3):
        result[row][3] *= MM
    return result


def face_transforms(assembly, part):
    result = {assembly["root_face"]: matrix_from_mm(assembly["root_transform_mm"])}
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
            # Both the fold designation and the named moving half-plane are
            # needed.  Reversing endpoints reverses axis and child_side, so
            # their product keeps the physical mountain/valley unchanged.
            sign = (1.0 if edge["mountain_valley"] == "valley" else -1.0) * edge["child_side"]
            theta = sign * math.radians(180.0 - edge["target_dihedral_deg"])
            result[edge["child_face"]] = parent @ Matrix.Translation(pivot) @ Matrix.Rotation(theta, 4, axis) @ Matrix.Translation(-pivot)
        if len(remaining) == len(unresolved):
            raise RuntimeError("validated fold tree could not be transformed")
        unresolved = remaining
    return result


def assert_nonempty(obj, label):
    if obj.type != "MESH" or not obj.data.vertices or not obj.data.polygons:
        raise RuntimeError("empty face cell: " + label)


def point_side(endpoints, point):
    a,b=line_world(endpoints); p=Vector((point[0]*MM,-point[1]*MM,0))
    return 1 if (b-a).cross(p-a).z >= 0 else -1


def main():
    args = arguments()
    root = Path(args.repo_root).resolve()
    plan_path = Path(args.plan).resolve()
    try:
        plan_path.relative_to(root)
    except ValueError as error:
        raise RuntimeError("--plan must be inside --repo-root") from error
    plan = load_plan(plan_path, root)
    export_path, print_path = root / plan["sources"]["export_json"], root / plan["sources"]["print_png"]
    output = resolve_output_boundary(root, args.output_dir, (plan_path, export_path, print_path))
    input_hashes = {"fold_plan": {"path": plan_path.relative_to(root).as_posix(), "sha256": sha256(plan_path)}, "export_json": {"path": plan["sources"]["export_json"], "sha256": sha256(export_path)}, "print_front": {"path": plan["sources"]["print_png"], "sha256": sha256(print_path)}}
    assert_replaceable(output, input_hashes, args.force)
    from tools.panel_input import load_bundle
    bundle = load_bundle(export_path, print_path, allow_folds=True)
    parts = {part["id"]: part for part in bundle["parts"]}
    staging = create_staging(output)
    try:
        texture_dir = staging / "textures"
        texture_dir.mkdir()
        texture_path = texture_dir / "print-front.png"
        shutil.copyfile(print_path, texture_path)
        _, collection, _ = setup_scene()
        front = front_material(texture_path)
        bpy.data.images["PF_PRINT_FRONT_SOURCE"].filepath = "//textures/print-front.png"
        paper = paper_material()
        folds, flat_instances, assembly_records = [], [], []
        for assembly in plan["assemblies"]:
            part = parts[assembly["part_id"]]
            flat_base = Matrix.Translation(Vector((part["bounds_mm"][0] * MM, -part["bounds_mm"][1] * MM, 0.0)))
            signatures, transforms = face_signatures(assembly), face_transforms(assembly, part)
            for face, signature in signatures.items():
                obj = make_panel(part, bundle["thickness_mm"], bundle["print_range_mm"], front, paper, collection)
                obj.name = "PF_FACE_" + assembly["id"] + "_" + face
                for edge in assembly["folds"]:
                    cut_half_flat(obj, fold_source(part, edge["fold_id"])["endpoints_mm"], signature[edge["fold_id"]] > 0)
                assert_nonempty(obj, assembly["id"] + "/" + face)
                obj.matrix_world = transforms[face] @ flat_base
                obj["pf_face_id"] = face
                obj["pf_flat_base_matrix"] = [list(row) for row in flat_base]
                contained=[]
                for hole in part["holes"]:
                    center=[sum(item["anchor_mm"][axis] for item in hole)/len(hole) for axis in (0,1)]
                    if all(point_side(fold_source(part, edge["fold_id"])["endpoints_mm"], center) == signature[edge["fold_id"]] for edge in assembly["folds"]): contained.append(hole)
                obj["pf_source_holes"] = _json.dumps(contained, separators=(",",":"))
            for edge in assembly["folds"]:
                source = fold_source(part, edge["fold_id"])
                folds.append({"assembly": assembly["id"], "fold_id": edge["fold_id"], "parent": edge["parent_face"], "child": edge["child_face"], "dihedral_deg": edge["target_dihedral_deg"], "rotation_from_flat_deg": (1 if edge["mountain_valley"] == "valley" else -1) * edge["child_side"] * (180 - edge["target_dihedral_deg"]), "endpoints_mm": source["endpoints_mm"]})
            assembly_records.append({"id":assembly["id"],"root_face":assembly["root_face"],"root_transform_mm":assembly["root_transform_mm"]})
        for instance in plan["flat_instances"]:
            part = parts[instance["part_id"]]
            obj = make_panel(part, bundle["thickness_mm"], bundle["print_range_mm"], front, paper, collection)
            obj.name = "PF_FLAT_" + instance["id"]
            flat_base = Matrix.Translation(Vector((part["bounds_mm"][0] * MM, -part["bounds_mm"][1] * MM, 0.0)))
            obj.matrix_world = matrix_from_mm(instance["transform_mm"]) @ flat_base
            obj["pf_flat_instance_id"] = instance["id"]
            obj["pf_flat_base_matrix"] = [list(row) for row in flat_base]
            flat_instances.append({"id": instance["id"], "part_id": instance["part_id"], "transform_mm": instance["transform_mm"]})
        bpy.ops.wm.save_as_mainfile(filepath=str(staging / "assembly.blend"))
        selected={(assembly["part_id"],edge["fold_id"]) for assembly in plan["assemblies"] for edge in assembly["folds"]}
        unselected=[{"part_id":part["id"],"fold_ids":[fold["id"] for fold in part.get("folds",[]) if (part["id"],fold["id"]) not in selected]} for part in bundle["parts"]]
        unselected=[item for item in unselected if item["fold_ids"]]
        (staging / "fold-manifest.json").write_text(json.dumps({"manifest_version": 1, "model": "rigid-mid-plane-v2", "input_hashes": input_hashes, "limitations": ["no bend radius", "no thickness collision guarantee", "no manufacturing guarantee"], "assemblies":assembly_records, "folds": folds, "flat_instances": flat_instances, "unselected_source_folds":unselected}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        provisional = {name: sha256(staging / name) for name in sorted(OUTPUT_NAMES - {"verification.json"})}
        (staging / "build-manifest.json").write_text(json.dumps({"manifest_version": 1, "input_hashes": input_hashes, "output_hashes": provisional}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        with tempfile.TemporaryDirectory(prefix="fold-verification-") as temporary:
            report = Path(temporary) / "verification.json"
            subprocess.run([bpy.app.binary_path, "--background", str(staging / "assembly.blend"), "--python-exit-code", "1", "--python", str(Path(__file__).with_name("verify_fold_assembly.py")), "--", "--bundle", str(staging), "--report", str(report)], check=True)
            shutil.copyfile(report, staging / "verification.json")
        final_hashes = {name: sha256(staging / name) for name in sorted(OUTPUT_NAMES)}
        (staging / "build-manifest.json").write_text(json.dumps({"manifest_version": 1, "input_hashes": input_hashes, "output_hashes": final_hashes}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        publish_staging(staging, output)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


if __name__ == "__main__":
    main()
