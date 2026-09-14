"""Validate the deterministic assembly plan produced from human-readable sources.

This is deliberately not a document reader.  A Codex skill reads drawings, PDFs or
notes and writes this private plan; this module only proves that the stated fold
tree is geometrically and semantically unambiguous before Blender is started.
"""
from __future__ import annotations

import json, math
from pathlib import Path

from tools.panel_input import InputError, load_bundle

SCHEMA = "paper-fixture-fold-plan-v1"
EPS = 1e-6

def _num(v, label):
    if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v):
        raise InputError(f"{label} must be finite")
    return float(v)

def _point(v, label):
    if not isinstance(v, list) or len(v) != 2: raise InputError(f"{label} must be [x, y]")
    return (_num(v[0], label+"[0]"), _num(v[1], label+"[1]"))

def _cross(a,b,c): return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
def _on_segment(p,a,b):
    return abs(_cross(a,b,p)) <= EPS and min(a[0],b[0])-EPS <= p[0] <= max(a[0],b[0])+EPS and min(a[1],b[1])-EPS <= p[1] <= max(a[1],b[1])+EPS
def _segments_intersect(a,b,c,d):
    return (_on_segment(a,c,d) or _on_segment(b,c,d) or _on_segment(c,a,b) or _on_segment(d,a,b) or
            (_cross(a,b,c)>EPS) != (_cross(a,b,d)>EPS) and (_cross(c,d,a)>EPS) != (_cross(c,d,b)>EPS))

def _anchors(path): return [tuple(p["anchor_mm"]) for p in path]
def _boundary(point, path):
    pts = _anchors(path)
    return any(_on_segment(point, pts[i], pts[(i+1)%len(pts)]) for i in range(len(pts)))

def validate_plan(payload, repo_root):
    """Return a normalized plan, or an actionable InputError.

    Initial geometry accepts fold endpoints on straight outer-boundary segments.
    A curved-boundary endpoint is rejected explicitly until its intersection
    routine is measured in Blender; this prevents silent approximate hinges.
    """
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA: raise InputError(f"schema must be {SCHEMA}")
    unknown = set(payload) - {"schema", "sources", "assemblies", "evidence"}
    if unknown: raise InputError("unknown fold plan fields: " + ", ".join(sorted(unknown)))
    src = payload.get("sources")
    if not isinstance(src, dict) or set(src) != {"export_json", "print_png"}: raise InputError("sources must contain export_json and print_png")
    root=Path(repo_root).resolve()
    paths=[]
    for key in ("export_json","print_png"):
        value=src[key]
        if not isinstance(value,str) or Path(value).is_absolute() or ".." in Path(value).parts: raise InputError(f"sources.{key} must be a repository-relative path")
        p=(root/value).resolve()
        if not p.is_file(): raise InputError(f"sources.{key} is missing")
        paths.append(p)
    bundle=load_bundle(*paths, allow_folds=True); parts={p["id"]:p for p in bundle["parts"]}
    # Intake deliberately leaves boundary relation undecided; resolve it here.
    for part in parts.values():
        seen_lines=[]
        for fold in part.get("folds",[]):
            ends=fold.get("endpoints_mm")
            if not isinstance(ends,list) or len(ends)!=2: raise InputError(f"{part['id']}.{fold.get('id')}: endpoints are invalid")
            a=_point(ends[0],'fold endpoint'); b=_point(ends[1],'fold endpoint')
            if a==b: raise InputError(f"{part['id']}.{fold.get('id')}: fold is degenerate")
            if not _boundary(a,part['outer']) or not _boundary(b,part['outer']): raise InputError(f"{part['id']}.{fold.get('id')}: endpoints must lie on outer boundary")
            for hole in part['holes']:
                pts=_anchors(hole)
                if any(_segments_intersect(a,b,pts[i],pts[(i+1)%len(pts)]) for i in range(len(pts))): raise InputError(f"{part['id']}.{fold.get('id')}: fold intersects a hole")
            if any(_segments_intersect(a,b,c,d) for c,d in seen_lines): raise InputError(f"{part['id']}.{fold.get('id')}: fold intersects another fold")
            seen_lines.append((a,b))
    assemblies=payload.get("assemblies")
    if not isinstance(assemblies,list) or not assemblies: raise InputError("assemblies must be non-empty")
    normalized=[]; seen=set()
    for index,a in enumerate(assemblies):
        label=f"assemblies[{index}]"
        if not isinstance(a,dict) or set(a)-{"id","part_id","root_face","root_transform_mm","folds"}: raise InputError(label+" has unknown fields")
        aid=a.get("id"); part_id=a.get("part_id")
        if not isinstance(aid,str) or not aid or aid in seen: raise InputError(label+".id must be unique")
        seen.add(aid)
        if part_id not in parts: raise InputError(label+".part_id is unknown")
        root_face=a.get("root_face")
        if not isinstance(root_face,str) or not root_face: raise InputError(label+".root_face is required")
        folds=a.get("folds")
        if not isinstance(folds,list) or not folds: raise InputError(label+".folds must be non-empty")
        ids={root_face}; children=set(); edges=[]; source_ids={x.get("id") for x in parts[part_id].get("folds", [])}
        for fi,f in enumerate(folds):
            fl=f"{label}.folds[{fi}]"
            required={"fold_id","parent_face","child_face","child_side","mountain_valley","viewed_from","target_dihedral_deg"}
            if not isinstance(f,dict) or set(f)!=required: raise InputError(fl+" fields must be "+", ".join(sorted(required)))
            for k in ("fold_id","parent_face","child_face"):
                if not isinstance(f[k],str) or not f[k]: raise InputError(fl+"."+k+" must be non-empty")
            if f["parent_face"]==f["child_face"]: raise InputError(fl+" cannot self-connect")
            if f["fold_id"] not in source_ids: raise InputError(fl+f".fold_id {f['fold_id']!r} is absent from {part_id}")
            if f["child_face"] in children: raise InputError(fl+".child_face already has a moving parent")
            if f["mountain_valley"] not in {"mountain","valley"} or f["viewed_from"]!="print_front": raise InputError(fl+" requires mountain/valley viewed_from print_front")
            if f["child_side"] not in {"left", "right"}: raise InputError(fl+".child_side must be left or right when walking endpoints_mm[0] to endpoints_mm[1] on print_front")
            dihedral=_num(f["target_dihedral_deg"], fl+".target_dihedral_deg")
            if not 0 < dihedral < 180: raise InputError(fl+".target_dihedral_deg must be between 0 and 180")
            children.add(f["child_face"]); ids.update((f["parent_face"],f["child_face"])); edges.append({**f,"target_dihedral_deg":dihedral,"child_side": 1 if f["child_side"] == "right" else -1})
        if root_face in children: raise InputError(label+".root_face must not move")
        if len(edges) != len(ids)-1: raise InputError(label+" fold graph must be a tree")
        reached={root_face}
        while True:
            add={e["child_face"] for e in edges if e["parent_face"] in reached}
            if add <= reached: break
            reached |= add
        if reached != ids: raise InputError(label+" fold graph is disconnected or cyclic")
        normalized.append({"id":aid,"part_id":part_id,"root_face":root_face,"folds":edges})
    return {"schema":SCHEMA,"sources":{"export_json":str(paths[0].relative_to(root)),"print_png":str(paths[1].relative_to(root))},"assemblies":normalized,"thickness_mm":bundle["thickness_mm"]}

def load_plan(path, repo_root):
    try: payload=json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError,json.JSONDecodeError) as e: raise InputError(f"cannot read fold plan: {e}") from e
    return validate_plan(payload, repo_root)
