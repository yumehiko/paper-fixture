"""Build an editable, self-contained Blender assembly bundle from placement JSON.

Run with Blender 5.2.1::

  Blender --background --python-exit-code 1 --python tools/build_assembly_bundle.py -- \\
    --input samples/placement/three-shelf-placement.json --repo-root . \\
    --output-dir build/assembly/three-shelf
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.assembly_input import evaluate_checks, load_placement
from tools.build_blender_panels import add_spline, paper_material, front_material, MM
from tools.assembly_bundle_output import (
    OUTPUT_NAMES, assert_replaceable, create_staging, publish_staging,
    resolve_output_boundary, sha256,
)


BLENDER_VERSION = "5.2.1"
MANIFEST_VERSION = 1
def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])


def make_panel(part, thickness_mm, print_range, front, paper, collection, instance):
    """Make a fresh mesh for one instance; its local origin remains left/top."""
    curve = bpy.data.curves.new(f"PF_{instance['id']}_outline", "CURVE")
    curve.dimensions = "2D"
    curve.fill_mode = "BOTH"
    curve.resolution_u = curve.render_resolution_u = 12
    curve.extrude = thickness_mm * MM / 2
    curve.use_fill_caps = True
    add_spline(curve, part["outer"], part["bounds_mm"], wants_ccw=True)
    for hole in part["holes"]:
        add_spline(curve, hole, part["bounds_mm"], wants_ccw=False)
    curve.materials.append(front)
    curve.materials.append(paper)
    object_ = bpy.data.objects.new(f"PF_INSTANCE_{instance['id']}", curve)
    collection.objects.link(object_)
    bpy.context.view_layer.objects.active = object_
    object_.select_set(True)
    bpy.ops.object.convert(target="MESH")
    object_ = bpy.context.object
    object_.name = f"PF_INSTANCE_{instance['id']}"
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.remove_doubles(threshold=1e-7)
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode="OBJECT")
    uv = object_.data.uv_layers.new(name="PF_PRINT_UV")
    px0, py0, px1, py1 = print_range
    xmin, ymin, _, _ = part["bounds_mm"]
    for polygon in object_.data.polygons:
        polygon.material_index = 0 if polygon.normal.z > .9 else 1
        for loop_index in polygon.loop_indices:
            vertex = object_.data.vertices[object_.data.loops[loop_index].vertex_index]
            global_x = vertex.co.x / MM + xmin
            global_y = -vertex.co.y / MM + ymin
            uv.data[loop_index].uv = ((global_x - px0) / (px1 - px0), 1 - (global_y - py0) / (py1 - py0))
    object_.location = [value * MM for value in instance["translation_mm"]]
    object_.rotation_mode = "XYZ"
    object_.rotation_euler = [math.radians(value) for value in instance["rotation_deg_xyz"]]
    object_.scale = (1, 1, 1)
    object_["pf_instance_id"] = instance["id"]
    object_["pf_part_id"] = instance["part_id"]
    object_["pf_input_translation_mm"] = instance["translation_mm"]
    object_["pf_input_rotation_deg_xyz"] = instance["rotation_deg_xyz"]
    object_["pf_resolved_matrix_mm"] = json.dumps(instance["matrix_mm"], separators=(",", ":"))
    object_["pf_source_bounds_mm"] = list(part["bounds_mm"])
    object_["pf_print_range_mm"] = list(print_range)
    object_["pf_source_holes"] = json.dumps(part["holes"], separators=(",", ":"))
    object_["pf_front_normal_local"] = [0., 0., 1.]
    object_["pf_thickness_mm"] = thickness_mm
    object_["pf_thickness_reference"] = "local Z=0 is the mid-plane; front print is +Z"
    object_["pf_local_axes"] = "origin=part bounding-box upper-left; +X=artboard right; +Y=artboard up; +Z=front"
    object_["pf_uv_mapping"] = "artboard print range, U=+X, V=artboard +Y (PNG rows are top-down)"
    object_.select_set(False)
    return object_


def point_camera(camera, location, target):
    camera.location = location
    camera.rotation_euler = (Vector(target) - Vector(location)).to_track_quat("-Z", "Y").to_euler()


def setup_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x, scene.render.resolution_y = 1200, 900
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.world.color = (0.055, 0.055, 0.055)
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.length_unit = "MILLIMETERS"
    scene.unit_settings.scale_length = MM
    collection = bpy.data.collections.new("PF_ASSEMBLY_INSTANCES")
    scene.collection.children.link(collection)
    camera = bpy.data.objects.new("PF_ASSEMBLY_CAMERA", bpy.data.cameras.new("PF_ASSEMBLY_CAMERA"))
    camera.data.lens = 48
    scene.collection.objects.link(camera)
    scene.camera = camera
    for name, location in (("PF_ASSEMBLY_KEY", (1.8, -2.2, 2.5)), ("PF_ASSEMBLY_FILL", (-1.2, -0.8, 1.5))):
        light = bpy.data.objects.new(name, bpy.data.lights.new(name, "AREA"))
        light.data.energy, light.data.shape, light.data.size = 900, "DISK", 2.0
        light.location = location
        point_camera(light, location, (0.18, -0.15, 0.23))
        scene.collection.objects.link(light)
    return scene, collection, camera


def render_previews(scene, camera, instances, output):
    aabbs = [item["world_aabb_mm"] for item in instances]
    minimum = [min(aabb[axis][0] for aabb in aabbs) * MM for axis in "xyz"]
    maximum = [max(aabb[axis][1] for aabb in aabbs) * MM for axis in "xyz"]
    target = [(a + b) / 2 for a, b in zip(minimum, maximum)]
    span = max(b - a for a, b in zip(minimum, maximum))
    point_camera(camera, (target[0] + span * 1.35, target[1] - span * 1.65, target[2] + span * 1.15), target)
    scene.render.filepath = str(output / "preview-perspective.png")
    bpy.ops.render.render(write_still=True)
    point_camera(camera, (target[0], target[1] - span * 2.4, target[2]), target)
    scene.render.filepath = str(output / "preview-reference.png")
    bpy.ops.render.render(write_still=True)


def manifest_instances(instances):
    keys = ("id", "part_id", "translation_mm", "rotation_deg_xyz", "matrix_mm")
    return [{**{key: item[key] for key in keys},
             "front_normal_world": [item["matrix_mm"][row][2] for row in range(3)]}
            for item in instances]


def main():
    args = arguments()
    root = Path(args.repo_root).resolve()
    input_path = Path(args.input).resolve()
    try:
        input_path.relative_to(root)
    except ValueError as error:
        raise RuntimeError("--input must be inside --repo-root") from error
    resolved = load_placement(input_path, root)
    checks = evaluate_checks(resolved)
    bundle_source = root / resolved["sources"]["panels"]
    image_source = root / resolved["sources"]["print_front"]
    input_hashes = {
        "placement": {"path": input_path.relative_to(root).as_posix(), "sha256": sha256(input_path)},
        "panels": {"path": resolved["sources"]["panels"], "sha256": sha256(bundle_source)},
        "print_front": {"path": resolved["sources"]["print_front"], "sha256": sha256(image_source)},
    }
    output = resolve_output_boundary(root, args.output_dir, (input_path, bundle_source, image_source))
    assert_replaceable(output, input_hashes, args.force)
    from tools.panel_input import load_bundle
    bundle = load_bundle(bundle_source, image_source)
    staging = create_staging(output)
    try:
        texture_dir = staging / "textures"
        texture_dir.mkdir()
        texture = texture_dir / "print-front.png"
        shutil.copyfile(image_source, texture)
        scene, collection, camera = setup_scene()
        front = front_material(texture)
        image = bpy.data.images["PF_PRINT_FRONT_SOURCE"]
        image.filepath = "//textures/print-front.png"
        front["pf_source_png"] = image.filepath
        paper = paper_material()
        parts = {part["id"]: part for part in bundle["parts"]}
        objects = [make_panel(parts[item["part_id"]], bundle["thickness_mm"], bundle["print_range_mm"], front, paper, collection, item) for item in resolved["instances"]]
        scene["pf_stage"] = "stage-4-assembly; transforms are editable instance placement"
        scene["pf_source_placement"] = input_path.relative_to(root).as_posix()
        scene["pf_blender_version_required"] = BLENDER_VERSION
        bpy.ops.wm.save_as_mainfile(filepath=str(staging / "assembly.blend"))
        render_previews(scene, camera, resolved["instances"], staging)
        # The provisional manifest lets the separate Blender process verify the
        # texture and instance contract before the final report is hashed.
        provisional_hashes = {name: sha256(staging / name) for name in sorted(OUTPUT_NAMES - {"verification.json"})}
        provisional_manifest = {"manifest_version": MANIFEST_VERSION, "blender_version": BLENDER_VERSION,
                                "input_hashes": input_hashes,
                                "instances": manifest_instances(resolved["instances"]),
                                "output_hashes": provisional_hashes}
        (staging / "build-manifest.json").write_text(json.dumps(provisional_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        with tempfile.TemporaryDirectory(prefix="assembly-verification-") as temporary:
            external_report = Path(temporary) / "verification.json"
            subprocess.run([bpy.app.binary_path, "--background", str(staging / "assembly.blend"), "--python-exit-code", "1", "--python",
                            str(Path(__file__).with_name("verify_assembly_bundle.py")), "--", "--bundle", str(staging),
                            "--report", str(external_report)], check=True)
            verification = json.loads(external_report.read_text(encoding="utf-8"))
        verification["input_checks"] = checks
        (staging / "verification.json").write_text(json.dumps(verification, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        hashes = {name: sha256(staging / name) for name in sorted(OUTPUT_NAMES)}
        manifest = {"manifest_version": MANIFEST_VERSION, "blender_version": BLENDER_VERSION,
                    "input_hashes": input_hashes,
                    "instances": manifest_instances(resolved["instances"]),
                    "output_hashes": hashes}
        (staging / "build-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        publish_staging(staging, output)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


if __name__ == "__main__":
    main()
