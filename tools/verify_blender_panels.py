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
        front_faces = sum(1 for polygon in mesh.polygons if polygon.normal.z > 0.9 and polygon.material_index == 0)
        other_faces = sum(1 for polygon in mesh.polygons if polygon.normal.z <= 0.9 and polygon.material_index == 1)
        holes_open = [hole_is_open(object_, hole, part["bounds_mm"]) for hole in part["holes"]]
        finding = {"id": part["id"], "mesh_vertices": len(mesh.vertices), "mesh_faces": len(mesh.polygons),
                   "closed_manifold": closed, "thickness_mm": thickness, "front_faces_with_print": front_faces,
                   "back_and_edge_faces_with_paper": other_faces, "holes_open": holes_open}
        if not closed or abs(thickness - bundle["thickness_mm"]) > 1e-5 or front_faces == 0 or other_faces == 0 or not all(holes_open):
            raise RuntimeError(f"panel verification failed: {finding}")
        findings.append(finding)
    report = {"blend": bpy.data.filepath, "reopened": True, "expected_thickness_mm": bundle["thickness_mm"], "parts": findings}
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
