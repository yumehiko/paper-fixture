"""Separate-process verification of folded cell geometry and transforms."""
import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector


def matrix_property(obj):
    return Matrix(obj["pf_flat_base_matrix"])


def face_transform(obj):
    return obj.matrix_world @ matrix_property(obj).inverted()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else [])
    bundle = Path(args.bundle)
    manifest = json.loads((bundle / "fold-manifest.json").read_text())
    folds, faces = [], []
    for obj in bpy.data.objects:
        if obj.name.startswith("PF_FACE_"):
            if obj.type != "MESH" or not obj.data.polygons or not obj.data.vertices:
                raise RuntimeError("empty editable face " + obj.name)
            if "PF_PRINT_UV" not in obj.data.uv_layers:
                raise RuntimeError("missing print UV " + obj.name)
            zs = [vertex.co.z for vertex in obj.data.vertices]
            if max(zs) - min(zs) <= 1e-8:
                raise RuntimeError("lost paper thickness " + obj.name)
            faces.append({"name": obj.name, "vertices": len(obj.data.vertices), "polygons": len(obj.data.polygons), "uv": "PF_PRINT_UV", "local_thickness_m": max(zs) - min(zs)})
    for fold in manifest["folds"]:
        prefix = "PF_FACE_" + fold["assembly"] + "_"
        parent = bpy.data.objects.get(prefix + fold["parent"])
        child = bpy.data.objects.get(prefix + fold["child"])
        if not parent or not child:
            raise RuntimeError("missing folded editable face " + fold["fold_id"])
        parent_normal = parent.matrix_world.to_3x3() @ Vector((0, 0, 1))
        child_normal = child.matrix_world.to_3x3() @ Vector((0, 0, 1))
        actual = math.degrees(math.acos(max(-1, min(1, parent_normal.normalized().dot(child_normal.normalized())))))
        expected = abs(fold["rotation_from_flat_deg"])
        if abs(actual - expected) > 0.01:
            raise RuntimeError("fold angle mismatch " + fold["fold_id"])
        hinge_errors = []
        for point in fold["endpoints_mm"]:
            flat = Vector((point[0] * .001, -point[1] * .001, 0, 1))
            hinge_errors.append((face_transform(parent) @ flat - face_transform(child) @ flat).length)
        if max(hinge_errors) > 1e-7:
            raise RuntimeError("hinge boundary mismatch " + fold["fold_id"])
        folds.append({"fold_id": fold["fold_id"], "angle_from_flat_deg": actual, "hinge_endpoint_error_m": max(hinge_errors), "editable_meshes": True})
    Path(args.report).write_text(json.dumps({"reopened": True, "faces": faces, "folds": folds}, indent=2) + "\n")


if __name__ == "__main__":
    main()
