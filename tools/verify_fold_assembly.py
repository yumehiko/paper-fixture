"""Separate-process verification of folded cell geometry and transforms."""
import argparse
import json
import math
import sys
from pathlib import Path

import bpy
import bmesh
from mathutils import Matrix, Vector


def sha256(path):
    import hashlib
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def matrix_property(obj):
    return Matrix(obj["pf_flat_base_matrix"])


def face_transform(obj):
    return obj.matrix_world @ matrix_property(obj).inverted()


def closed_manifold(obj):
    mesh=bmesh.new(); mesh.from_mesh(obj.data)
    result=all(len(edge.link_faces)==2 for edge in mesh.edges)
    mesh.free(); return result


def hole_open(obj, hole):
    anchors=[item["anchor_mm"] for item in hole]
    x=sum(point[0] for point in anchors)/len(anchors); y=sum(point[1] for point in anchors)/len(anchors)
    bounds=obj.get("pf_source_bounds_mm")
    point=Vector(((x-bounds[0])*.001, -(y-bounds[1])*.001, .1))
    hit,_,_,_=obj.ray_cast(point, Vector((0,0,-1)))
    return not hit


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else [])
    bundle = Path(args.bundle)
    report_path = Path(args.report).resolve()
    if report_path.is_relative_to(bundle.resolve()):
        raise RuntimeError("--report must be outside --bundle so verification cannot alter bundle provenance")
    build = json.loads((bundle / "build-manifest.json").read_text())
    manifest = json.loads((bundle / "fold-manifest.json").read_text())
    if build.get("manifest_version") != 1 or manifest.get("manifest_version") != 1:
        raise RuntimeError("unsupported fold bundle manifest")
    if build.get("input_hashes") != manifest.get("input_hashes"):
        raise RuntimeError("fold/build input provenance mismatch")
    outputs = build.get("output_hashes")
    if not isinstance(outputs, dict):
        raise RuntimeError("build output hashes are missing")
    for name, expected in outputs.items():
        candidate = bundle / name
        if not candidate.is_file() or sha256(candidate) != expected:
            raise RuntimeError("bundle provenance mismatch " + name)
    texture = bundle / "textures/print-front.png"
    source_texture = manifest.get("input_hashes", {}).get("print_front", {}).get("sha256")
    if not isinstance(source_texture, str) or sha256(texture) != source_texture:
        raise RuntimeError("bundle texture does not match source input hash")
    folds, faces = [], []
    for obj in bpy.data.objects:
        if obj.name.startswith("PF_FACE_"):
            if obj.type != "MESH" or not obj.data.polygons or not obj.data.vertices:
                raise RuntimeError("empty editable face " + obj.name)
            if "PF_PRINT_UV" not in obj.data.uv_layers:
                raise RuntimeError("missing print UV " + obj.name)
            if not closed_manifold(obj):
                raise RuntimeError("face is not a closed manifold " + obj.name)
            zs = [vertex.co.z for vertex in obj.data.vertices]
            if max(zs) - min(zs) <= 1e-8:
                raise RuntimeError("lost paper thickness " + obj.name)
            holes=json.loads(obj.get("pf_source_holes", "[]"))
            if not all(hole_open(obj,hole) for hole in holes): raise RuntimeError("face hole is closed " + obj.name)
            faces.append({"name": obj.name, "vertices": len(obj.data.vertices), "polygons": len(obj.data.polygons), "uv": "PF_PRINT_UV", "closed_manifold":True, "holes_open":len(holes), "local_thickness_m": max(zs) - min(zs)})
    flat_instances=[]
    for item in manifest.get("flat_instances", []):
        obj=bpy.data.objects.get("PF_FLAT_" + item["id"])
        if obj is None or obj.type != "MESH" or not obj.data.polygons or "PF_PRINT_UV" not in obj.data.uv_layers:
            raise RuntimeError("missing editable flat instance " + item["id"])
        base=matrix_property(obj)
        # Flat objects retain their source base transform; compare only the
        # requested assembly transform in millimetres.
        actual=obj.matrix_world @ base.inverted()
        expected=Matrix(item["transform_mm"])
        for row in range(3): expected[row][3] *= .001
        if max(abs(actual[row][col]-expected[row][col]) for row in range(4) for col in range(4)) > 1e-7:
            raise RuntimeError("flat instance transform mismatch " + item["id"])
        flat_instances.append({"id":item["id"],"part_id":item["part_id"],"editable_mesh":True})
    for fold in manifest["folds"]:
        prefix = "PF_FACE_" + fold["assembly"] + "_"
        parent = bpy.data.objects.get(prefix + fold["parent"])
        child = bpy.data.objects.get(prefix + fold["child"])
        if not parent or not child:
            raise RuntimeError("missing folded editable face " + fold["fold_id"])
        parent_normal = parent.matrix_world.to_3x3() @ Vector((0, 0, 1))
        child_normal = child.matrix_world.to_3x3() @ Vector((0, 0, 1))
        parent_normal.normalize(); child_normal.normalize()
        a, b = fold["endpoints_mm"]
        source_axis = Vector((b[0] - a[0], -(b[1] - a[1]), 0.0)).normalized()
        world_axis = parent.matrix_world.to_3x3() @ source_axis
        world_axis.normalize()
        signed_actual = math.degrees(math.atan2(world_axis.dot(parent_normal.cross(child_normal)), parent_normal.dot(child_normal)))
        if abs(signed_actual - fold["rotation_from_flat_deg"]) > 0.01:
            raise RuntimeError("fold angle mismatch " + fold["fold_id"])
        hinge_errors = []
        for point in fold["endpoints_mm"]:
            flat = Vector((point[0] * .001, -point[1] * .001, 0, 1))
            hinge_errors.append((face_transform(parent) @ flat - face_transform(child) @ flat).length)
        if max(hinge_errors) > 1e-7:
            raise RuntimeError("hinge boundary mismatch " + fold["fold_id"])
        folds.append({"assembly": fold["assembly"], "fold_id": fold["fold_id"], "angle_from_flat_deg": abs(signed_actual), "signed_angle_from_flat_deg": signed_actual, "child_normal_world": list(child_normal), "hinge_endpoint_error_m": max(hinge_errors), "editable_meshes": True})
    roots=[]
    for assembly in manifest.get("assemblies", []):
        root=bpy.data.objects.get("PF_FACE_"+assembly["id"]+"_"+assembly["root_face"])
        if root is None: raise RuntimeError("missing root face "+assembly["id"])
        actual=face_transform(root); expected=Matrix(assembly["root_transform_mm"])
        for row in range(3): expected[row][3]*=.001
        rotation_error=max(abs(actual[row][column]-expected[row][column]) for row in range(3) for column in range(3))
        translation_error=max(abs(actual[row][3]-expected[row][3]) for row in range(3))
        if rotation_error>1e-6 or translation_error>1e-6: raise RuntimeError("root transform mismatch "+assembly["id"])
        roots.append({"assembly":assembly["id"],"root_face":assembly["root_face"],"max_rotation_element_error":rotation_error,"rotation_element_tolerance":1e-6,"max_translation_error_m":translation_error,"translation_tolerance_m":1e-6,"root_transform_verified":True})
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps({"reopened": True, "faces": faces, "roots":roots, "flat_instances":flat_instances, "folds": folds, "texture_sha256": source_texture, "source_input_hashes": manifest["input_hashes"]}, indent=2) + "\n")


if __name__ == "__main__":
    main()
