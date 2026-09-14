"""Create editable, flat Blender panels from an Illustrator export bundle.

Run this through Blender, for example::

  Blender --background --python tools/build_blender_panels.py -- \
    --export-json build/.../export.json --print-png build/.../print-front.png \
    --output-dir build/blender-panels-r3/curve-hole
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from panel_input import load_bundle, signed_area


MM = 0.001
PAPER_RGB = (0.78, 0.73, 0.62, 1.0)
CURVE_RESOLUTION_PER_BEZIER = 12


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export-json", required=True)
    parser.add_argument("--print-png", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else [])


def point_local(point, bounds):
    """AI upper-left coordinates to a part-local, front-facing Blender plane."""
    return ((point[0] - bounds[0]) * MM, -(point[1] - bounds[1]) * MM)


def reverse_path(points):
    return [
        {"anchor_mm": item["anchor_mm"], "in_handle_mm": item["out_handle_mm"], "out_handle_mm": item["in_handle_mm"]}
        for item in reversed(points)
    ]


def path_with_winding(points, bounds, wants_ccw):
    anchors = [point_local(point["anchor_mm"], bounds) for point in points]
    is_ccw = signed_area(anchors) > 0
    return points if is_ccw == wants_ccw else reverse_path(points)


def add_spline(curve, points, bounds, wants_ccw):
    points = path_with_winding(points, bounds, wants_ccw)
    spline = curve.splines.new("BEZIER")
    spline.bezier_points.add(len(points) - 1)
    for bezier, point in zip(spline.bezier_points, points):
        bezier.co = (*point_local(point["anchor_mm"], bounds), 0.0)
        bezier.handle_left = (*point_local(point["in_handle_mm"], bounds), 0.0)
        bezier.handle_right = (*point_local(point["out_handle_mm"], bounds), 0.0)
        bezier.handle_left_type = "FREE"
        bezier.handle_right_type = "FREE"
    spline.use_cyclic_u = True


def paper_material():
    material = bpy.data.materials.new("PF_PAPER_BASE")
    material.use_nodes = True
    principled = material.node_tree.nodes.get("Principled BSDF")
    principled.inputs["Base Color"].default_value = PAPER_RGB
    principled.inputs["Roughness"].default_value = 0.82
    material["pf_surface"] = "back-and-edge-paper-base"
    return material


def front_material(image_path):
    material = bpy.data.materials.new("PF_PRINT_FRONT")
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    principled = nodes.get("Principled BSDF")
    principled.inputs["Roughness"].default_value = 0.76
    image = bpy.data.images.load(str(image_path), check_existing=True)
    image.name = "PF_PRINT_FRONT_SOURCE"
    texture = nodes.new("ShaderNodeTexImage")
    texture.image = image
    texture.extension = "CLIP"
    uv = nodes.new("ShaderNodeUVMap")
    uv.uv_map = "PF_PRINT_UV"
    mix = nodes.new("ShaderNodeMixRGB")
    mix.blend_type = "MIX"
    mix.inputs[1].default_value = PAPER_RGB
    links.new(uv.outputs["UV"], texture.inputs["Vector"])
    links.new(texture.outputs["Alpha"], mix.inputs[0])
    links.new(texture.outputs["Color"], mix.inputs[2])
    links.new(mix.outputs["Color"], principled.inputs["Base Color"])
    material["pf_surface"] = "front-print-only"
    return material


def make_panel(part, thickness_mm, print_range, front, paper, collection):
    curve = bpy.data.curves.new(f"PF_{part['id']}_outline", "CURVE")
    curve.dimensions = "2D"
    curve.fill_mode = "BOTH"
    curve.resolution_u = CURVE_RESOLUTION_PER_BEZIER
    curve.render_resolution_u = CURVE_RESOLUTION_PER_BEZIER
    curve.resolution_u = CURVE_RESOLUTION_PER_BEZIER
    curve.extrude = thickness_mm * MM / 2.0
    curve.use_fill_caps = True
    curve.resolution_u = CURVE_RESOLUTION_PER_BEZIER
    curve.twist_smooth = 0.0
    # Clockwise holes and a counter-clockwise outer boundary yield a true cutout.
    add_spline(curve, part["outer"], part["bounds_mm"], wants_ccw=True)
    for hole in part["holes"]:
        add_spline(curve, hole, part["bounds_mm"], wants_ccw=False)
    curve.materials.append(front)
    curve.materials.append(paper)
    object_ = bpy.data.objects.new(f"PF_PART_{part['id']}", curve)
    collection.objects.link(object_)
    xmin, ymin, _, _ = part["bounds_mm"]
    object_.location = (xmin * MM, -ymin * MM, 0.0)
    bpy.context.view_layer.objects.active = object_
    object_.select_set(True)
    bpy.ops.object.convert(target="MESH")
    object_ = bpy.context.object
    object_.name = f"PF_PART_{part['id']}"
    # Curve conversion keeps cap and wall vertices separate. Weld matching vertices
    # so the saved editable mesh is a closed solid, not merely coincident surfaces.
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.remove_doubles(threshold=1e-7)
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode="OBJECT")
    uv_layer = object_.data.uv_layers.new(name="PF_PRINT_UV")
    px0, py0, px1, py1 = print_range
    for polygon in object_.data.polygons:
        polygon.material_index = 0 if polygon.normal.z > 0.9 else 1
        for loop_index in polygon.loop_indices:
            vertex = object_.data.vertices[object_.data.loops[loop_index].vertex_index]
            global_x = vertex.co.x / MM + xmin
            global_y = -vertex.co.y / MM + ymin
            uv_layer.data[loop_index].uv = ((global_x - px0) / (px1 - px0), 1.0 - (global_y - py0) / (py1 - py0))
    object_["pf_part_id"] = part["id"]
    object_["pf_source_bounds_mm"] = list(part["bounds_mm"])
    object_["pf_front_normal_local"] = [0.0, 0.0, 1.0]
    object_["pf_thickness_mm"] = thickness_mm
    object_["pf_thickness_reference"] = "local Z=0 is the mid-plane; front print is +Z"
    object_["pf_local_axes"] = "origin=part bounding-box upper-left; +X=artboard right; +Y=artboard up; +Z=front"
    object_["pf_uv_mapping"] = "artboard print range, U=+X, V=artboard +Y (PNG rows are top-down)"
    object_["pf_curve_resolution_per_bezier"] = CURVE_RESOLUTION_PER_BEZIER
    object_.select_set(False)
    return object_


def setup_scene(bounds):
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for old_collection in list(bpy.data.collections):
        if old_collection.name != "Collection":
            bpy.data.collections.remove(old_collection)
    collection = bpy.data.collections.new("PF_FLAT_PANELS_NON_ASSEMBLY")
    scene = bpy.context.scene
    # Blender 5.2.1 LTS exposes the realtime renderer as BLENDER_EEVEE.
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 1600
    scene.render.resolution_y = 900
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.world.color = (0.055, 0.055, 0.055)
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.length_unit = "MILLIMETERS"
    scene.unit_settings.scale_length = MM
    scene.collection.children.link(collection)
    xmin, ymin, xmax, ymax = bounds
    center = ((xmin + xmax) * MM / 2, -(ymin + ymax) * MM / 2)
    camera_data = bpy.data.cameras.new("PF_PREVIEW_CAMERA")
    camera = bpy.data.objects.new("PF_PREVIEW_CAMERA", camera_data)
    scene.collection.objects.link(camera)
    camera.location = (center[0], center[1], 2.0)
    camera.rotation_euler = (0.0, 0.0, 0.0)
    camera_data.type = "ORTHO"
    # Blender's ortho scale is the horizontal span.  Account for the 16:9
    # output so a portrait artboard cannot be cropped above/below.
    aspect = scene.render.resolution_x / scene.render.resolution_y
    camera_data.ortho_scale = max((xmax - xmin) * MM, (ymax - ymin) * MM * aspect) * 1.08
    scene.camera = camera
    for name, z in (("PF_PREVIEW_FRONT_LIGHT", 0.5), ("PF_PREVIEW_BACK_LIGHT", -0.5)):
        light_data = bpy.data.lights.new(name, "AREA")
        light_data.energy = 20.0
        light_data.shape = "DISK"
        light_data.size = 1.0
        light = bpy.data.objects.new(name, light_data)
        scene.collection.objects.link(light)
        light.location = (center[0], center[1], z)
        if z < 0:
            light.rotation_euler = (3.141592653589793, 0.0, 0.0)
    return camera, collection


def render(scene, camera, path, rear=False):
    if rear:
        camera.location.z = -2.0
        camera.rotation_euler = (0.0, 3.141592653589793, 0.0)
    else:
        camera.location.z = 2.0
        camera.rotation_euler = (0.0, 0.0, 0.0)
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def repo_relative(path):
    root = Path(__file__).resolve().parents[1]
    return Path(path).resolve().relative_to(root).as_posix()


def main():
    args = arguments()
    bundle = load_bundle(args.export_json, args.print_png)
    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    bounds = bundle["payload"]["coordinate_system"]["artboard_bounds_mm"]
    camera, collection = setup_scene(bounds)
    source_png = Path(args.print_png).resolve()
    front = front_material(source_png)
    # The source image remains external, but is linked relative to the saved
    # blend. A checkout containing both build trees can move as one directory.
    image = bpy.data.images["PF_PRINT_FRONT_SOURCE"]
    image.filepath = "//" + os.path.relpath(source_png, output)
    front["pf_source_png"] = image.filepath
    paper = paper_material()
    objects = [make_panel(part, bundle["thickness_mm"], bundle["print_range_mm"], front, paper, collection) for part in bundle["parts"]]
    scene = bpy.context.scene
    scene["pf_stage"] = "stage-3-flat-panels; no assembly placement applied"
    scene["pf_source_export_json"] = repo_relative(args.export_json)
    scene["pf_curve_resolution_per_bezier"] = CURVE_RESOLUTION_PER_BEZIER
    scene["pf_thickness_reference"] = "local Z=0 mid-plane; printed front at +thickness/2"
    scene["pf_texture_resolution_note"] = "Uses source PNG pixels over print.range_mm; no resampling is performed."
    bpy.ops.wm.save_as_mainfile(filepath=str(output / "panels.blend"))
    render(scene, camera, output / "preview-front.png")
    render(scene, camera, output / "preview-back.png", rear=True)
    (output / "build-manifest.json").write_text(json.dumps({
        "input": {
            "export_json": {"path": repo_relative(args.export_json), "sha256": sha256(args.export_json)},
            "print_png": {"path": repo_relative(args.print_png), "sha256": sha256(args.print_png)},
        },
        "outputs": {"blend": "panels.blend", "preview_front": "preview-front.png", "preview_back": "preview-back.png"},
        "part_ids": [object_["pf_part_id"] for object_ in objects],
        "thickness_mm": bundle["thickness_mm"], "curve_resolution_per_bezier": CURVE_RESOLUTION_PER_BEZIER,
        "stage": "flat panels only; not an assembly",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
