"""Re-open an assembly bundle and check editable instances and external texture."""
from __future__ import annotations
import argparse, hashlib, json, sys
from pathlib import Path
import bpy

def arguments():
    p = argparse.ArgumentParser(); p.add_argument("--bundle", required=True); p.add_argument("--report", required=True)
    return p.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
def sha(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for b in iter(lambda:f.read(1048576), b""): h.update(b)
    return h.hexdigest()
def main():
    a=arguments(); bundle=Path(a.bundle).resolve(); manifest=json.loads((bundle/"build-manifest.json").read_text())
    expected=manifest["instances"]; objects=[]
    image_path=(bundle/"textures/print-front.png").resolve()
    for item in expected:
        o=bpy.data.objects.get("PF_INSTANCE_"+item["id"])
        if o is None or o.type != "MESH" or tuple(o.scale)!=(1,1,1): raise RuntimeError("missing editable scale-one instance: "+item["id"])
        if o.data.users != 1: raise RuntimeError("mesh data is shared: "+item["id"])
        if o.get("pf_part_id") != item["part_id"]: raise RuntimeError("part mapping mismatch: "+item["id"])
        objects.append({"id":item["id"],"mesh":o.data.name,"location_m":list(o.location),"rotation_rad":list(o.rotation_euler)})
    for material in bpy.data.materials:
        if material.name == "PF_PRINT_FRONT":
            nodes=[n for n in material.node_tree.nodes if n.bl_idname=="ShaderNodeTexImage"]
            if len(nodes)!=1 or Path(bpy.path.abspath(nodes[0].image.filepath)).resolve()!=image_path: raise RuntimeError("texture link is not bundle-relative")
            break
    else: raise RuntimeError("front material missing")
    report={"reopened":True,"instances":objects,"texture_sha256":sha(image_path),"texture_hash_matches_manifest":sha(image_path)==manifest["output_hashes"]["textures/print-front.png"]}
    if not report["texture_hash_matches_manifest"]: raise RuntimeError("texture hash mismatch")
    Path(a.report).write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
if __name__=="__main__": main()
