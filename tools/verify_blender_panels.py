"""Re-opened-Blender verification for a stage-3 panel .blend."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from panel_input import load_bundle


MM = 0.001
# Float32 mesh coordinates create a few 1e-5 mm at these artboard offsets.
TOLERANCE_MM = 5e-5


def arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--export-json", required=True)
    parser.add_argument("--print-png", required=True)
    parser.add_argument("--report", required=True)
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else [])


def hole_is_open(object_, hole, bounds):
    anchors = [point["anchor_mm"] for point in hole]
    x = sum(point[0] for point in anchors) / len(anchors)
    y = sum(point[1] for point in anchors) / len(anchors)
    origin = Vector(((x - bounds[0]) * MM, -(y - bounds[1]) * MM, 0.1))
    hit, _, _, _ = object_.ray_cast(origin, Vector((0, 0, -1)))
    return not hit


def expected_uv(vertex, bounds, print_range):
    px0, py0, px1, py1 = print_range
    global_x = vertex.co.x / MM + bounds[0]
    global_y = -vertex.co.y / MM + bounds[1]
    return ((global_x - px0) / (px1 - px0), 1.0 - (global_y - py0) / (py1 - py0))


def front_image_path(material):
    textures = [node for node in material.node_tree.nodes if node.bl_idname == "ShaderNodeTexImage"]
    if len(textures) != 1 or textures[0].image is None:
        return None
    return Path(bpy.path.abspath(textures[0].image.filepath)).resolve()


def main():
    args = arguments()
    bundle = load_bundle(args.export_json, args.print_png)
    findings = []
    for part in bundle["parts"]:
        object_ = bpy.data.objects.get(f"PF_PART_{part['id']}")
        if object_ is None or object_.type != "MESH":
            raise RuntimeError(f"missing editable mesh for {part['id']}")
        mesh = object_.data
        # BMesh exposes face incidence correctly even for the cap triangulation.
        checked_mesh = bmesh.new()
        checked_mesh.from_mesh(mesh)
        closed = all(len(edge.link_faces) == 2 for edge in checked_mesh.edges)
        checked_mesh.free()
        z_values = [vertex.co.z / MM for vertex in mesh.vertices]
        thickness = max(z_values) - min(z_values)
        x_values = [vertex.co.x / MM for vertex in mesh.vertices]
        y_values = [vertex.co.y / MM for vertex in mesh.vertices]
        size_mm = [max(x_values) - min(x_values), max(y_values) - min(y_values)]
        expected_size_mm = [part["bounds_mm"][2] - part["bounds_mm"][0], part["bounds_mm"][3] - part["bounds_mm"][1]]
        front = [polygon for polygon in mesh.polygons if polygon.normal.z > 0.9]
        back = [polygon for polygon in mesh.polygons if polygon.normal.z < -0.9]
        edge = [polygon for polygon in mesh.polygons if abs(polygon.normal.z) < 0.1]
        front_material_ok = bool(front) and all(polygon.material_index == 0 for polygon in front)
        back_material_ok = bool(back) and all(polygon.material_index == 1 for polygon in back)
        edge_material_ok = bool(edge) and all(polygon.material_index == 1 for polygon in edge)
        uv_layer = mesh.uv_layers.get("PF_PRINT_UV")
        uv_ok = uv_layer is not None
        if uv_layer:
            for polygon in front:
                for loop_index in polygon.loop_indices:
                    vertex = mesh.vertices[mesh.loops[loop_index].vertex_index]
                    expected = expected_uv(vertex, part["bounds_mm"], bundle["print_range_mm"])
                    actual = uv_layer.data[loop_index].uv
                    if abs(actual.x - expected[0]) > 1e-6 or abs(actual.y - expected[1]) > 1e-6:
                        uv_ok = False
        material = mesh.materials[0] if len(mesh.materials) > 0 else None
        image_ok = material is not None and material.name == "PF_PRINT_FRONT" and front_image_path(material) == Path(args.print_png).resolve()
        holes_open = [hole_is_open(object_, hole, part["bounds_mm"]) for hole in part["holes"]]
        finding = {"id": part["id"], "mesh_vertices": len(mesh.vertices), "mesh_faces": len(mesh.polygons),
                   "closed_manifold": closed, "thickness_mm": thickness, "size_mm": size_mm,
                   "front_material_ok": front_material_ok, "back_material_ok": back_material_ok,
                   "edge_material_ok": edge_material_ok, "uv_ok": uv_ok, "print_image_link_ok": image_ok,
                   "holes_open": holes_open}
        if (not closed or abs(thickness - bundle["thickness_mm"]) > TOLERANCE_MM
                or any(abs(actual - expected) > TOLERANCE_MM for actual, expected in zip(size_mm, expected_size_mm))
                or not front_material_ok or not back_material_ok or not edge_material_ok or not uv_ok or not image_ok
                or not all(holes_open)):
            raise RuntimeError(f"panel verification failed: {finding}")
        findings.append(finding)
    report = {"blend": bpy.data.filepath, "reopened": True, "expected_thickness_mm": bundle["thickness_mm"], "parts": findings}
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
