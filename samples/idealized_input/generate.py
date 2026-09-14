"""Generate the two editable idealized Illustrator inputs from explicit millimetre data."""
# ruff: noqa: E501

from __future__ import annotations

import argparse
import json
import math
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from py_ai_illustrator.model import ControlPoint, Layer, LayerItemRef, Point
from py_ai_illustrator.model import Path as AiPath

from illustrator_agent import Artboard, Color, Document, Group
from illustrator_agent.production import (
    ProductionArtboard,
    ProductionContract,
    compile_reference_production,
    verify_reference_document,
)

SOURCE = Path(__file__).resolve()
INPUT = SOURCE.with_name("input.json")
MM_TO_PT = 72.0 / 25.4
CUT = Color(1.0, 0.0, 0.0)
CYAN = Color(0.0, 0.72, 0.86)
ORANGE = Color(1.0, 0.38, 0.05)
NAVY = Color(0.06, 0.13, 0.25)
WHITE = Color(1.0, 1.0, 1.0)
PAPER = Color(0.94, 0.94, 0.90)


def pt(value: float) -> float:
    return value * MM_TO_PT


def mm_pair(values: Iterable[float]) -> tuple[float, float]:
    x, y = values
    return pt(float(x)), pt(float(y))


def rounded_rectangle(item_id: str, width_mm: float, height_mm: float, radius_mm: float, *, name: str) -> AiPath:
    """A closed four-corner cubic-Bézier outline in part-local coordinates."""

    width, height, radius = pt(width_mm), pt(height_mm), pt(radius_mm)
    k = 0.5522847498307936
    return AiPath(
        id=item_id,
        name=name,
        fill=None,
        stroke=CUT,
        stroke_width=pt(0.35),
        points=[
            Point(radius, 0, in_handle=ControlPoint(radius - k * radius, 0), out_handle=ControlPoint(radius + k * radius, 0), smooth=True),
            Point(width - radius, 0, in_handle=ControlPoint(width - radius - k * radius, 0), out_handle=ControlPoint(width - radius + k * radius, 0), smooth=True),
            Point(width, radius, in_handle=ControlPoint(width, radius - k * radius), out_handle=ControlPoint(width, radius + k * radius), smooth=True),
            Point(width, height - radius, in_handle=ControlPoint(width, height - radius - k * radius), out_handle=ControlPoint(width, height - radius + k * radius), smooth=True),
            Point(width - radius, height, in_handle=ControlPoint(width - radius + k * radius, height), out_handle=ControlPoint(width - radius - k * radius, height), smooth=True),
            Point(radius, height, in_handle=ControlPoint(radius + k * radius, height), out_handle=ControlPoint(radius - k * radius, height), smooth=True),
            Point(0, height - radius, in_handle=ControlPoint(0, height - radius + k * radius), out_handle=ControlPoint(0, height - radius - k * radius), smooth=True),
            Point(0, radius, in_handle=ControlPoint(0, radius + k * radius), out_handle=ControlPoint(0, radius - k * radius), smooth=True),
        ],
    )


def rectangle(item_id: str, width_mm: float, height_mm: float, *, fill: Color, name: str, x_mm: float = 0, y_mm: float = 0) -> AiPath:
    x, y, width, height = pt(x_mm), pt(y_mm), pt(width_mm), pt(height_mm)
    return AiPath(id=item_id, name=name, fill=fill, stroke=None, points=[Point(x, y), Point(x + width, y), Point(x + width, y + height), Point(x, y + height)])


def ellipse(item_id: str, center_mm: tuple[float, float], diameter_mm: float, *, stroke: Color | None, fill: Color | None, name: str) -> AiPath:
    cx, cy = mm_pair(center_mm)
    radius = pt(diameter_mm / 2)
    k = 0.5522847498307936
    return AiPath(id=item_id, name=name, fill=fill, stroke=stroke, stroke_width=pt(0.35), points=[
        Point(cx + radius, cy, in_handle=ControlPoint(cx + radius, cy - k * radius), out_handle=ControlPoint(cx + radius, cy + k * radius), smooth=True),
        Point(cx, cy + radius, in_handle=ControlPoint(cx + k * radius, cy + radius), out_handle=ControlPoint(cx - k * radius, cy + radius), smooth=True),
        Point(cx - radius, cy, in_handle=ControlPoint(cx - radius, cy + k * radius), out_handle=ControlPoint(cx - radius, cy - k * radius), smooth=True),
        Point(cx, cy - radius, in_handle=ControlPoint(cx - k * radius, cy - radius), out_handle=ControlPoint(cx + k * radius, cy - radius), smooth=True),
    ])


def arrow(item_id: str, x_mm: float, y_mm: float) -> AiPath:
    x, y = pt(x_mm), pt(y_mm)
    return AiPath(id=item_id, name="FRONT +Y orientation arrow", fill=ORANGE, stroke=None, points=[Point(x, y), Point(x + pt(24), y), Point(x + pt(24), y + pt(35)), Point(x + pt(36), y + pt(35)), Point(x + pt(12), y + pt(58)), Point(x - pt(12), y + pt(35)), Point(x, y + pt(35))])


def group(item_id: str, name: str, paths: list[AiPath]) -> Group:
    return Group(id=item_id, name=name, paths=paths, item_order=[LayerItemRef("path", path.id) for path in paths])


def layer(item_id: str, name: str, groups: list[Group]) -> Layer:
    return Layer(id=item_id, name=name, groups=groups, item_order=[LayerItemRef("group", item.id) for item in groups])


def flip_path_y(path: AiPath, canvas_height_mm: float) -> AiPath:
    """Map the input's top-left, +Y-down coordinates to Illustrator coordinates."""

    canvas_height = pt(canvas_height_mm)

    def flip_handle(handle: ControlPoint | None) -> ControlPoint | None:
        if handle is None:
            return None
        return ControlPoint(handle.x, canvas_height - handle.y)

    points = [
        Point(
            point.x,
            canvas_height - point.y,
            in_handle=flip_handle(point.in_handle),
            out_handle=flip_handle(point.out_handle),
            smooth=point.smooth,
        )
        for point in path.points
    ]
    return AiPath(
        id=path.id,
        name=path.name,
        points=points,
        closed=path.closed,
        fill=path.fill,
        stroke=path.stroke,
        stroke_width=path.stroke_width,
        dash_pattern=list(path.dash_pattern),
        dash_offset=path.dash_offset,
        line_cap=path.line_cap,
        line_join=path.line_join,
        miter_limit=path.miter_limit,
        polarity=path.polarity,
        unknown=dict(path.unknown),
    )


def apply_input_coordinate_system(document: Document, canvas_height_mm: float) -> Document:
    """Apply the one top-left mm to Illustrator-coordinate conversion at the boundary."""

    for item_layer in document.layers:
        for item_group in item_layer.groups:
            item_group.paths = [
                flip_path_y(path, canvas_height_mm) for path in item_group.paths
            ]
    return document


@dataclass(frozen=True)
class Sample:
    key: str
    document: Document
    contract: ProductionContract


def small_sample(data: dict) -> Sample:
    spec = data["small_sample"]
    width, height = float(spec["width_mm"]), float(spec["height_mm"])
    part_id = spec["id"]
    cut_paths = [
        rounded_rectangle(f"cut.{part_id}.outer", width, height, float(spec["corner_radius_mm"]), name="CUT outer contour (Bézier R20)"),
        ellipse(f"cut.{part_id}.hole.01", tuple(spec["hole_center_mm"]), float(spec["hole_diameter_mm"]), stroke=CUT, fill=None, name="CUT hole φ24"),
    ]
    print_paths = [
        rectangle(f"print.{part_id}.base", width, height, fill=PAPER, name="print base"),
        rectangle(f"print.{part_id}.left-bar", 24, height, fill=CYAN, name="asymmetric left cyan bar"),
        arrow(f"print.{part_id}.orientation", 186, 76),
        ellipse(f"print.{part_id}.hole-window", tuple(spec["hole_center_mm"]), float(spec["hole_diameter_mm"]), stroke=None, fill=WHITE, name="hole location witness"),
    ]
    cut_group = group(f"group.cut.{part_id}", f"PF_PART_{part_id}", cut_paths)
    print_group = group(f"group.print.{part_id}", f"PF_PART_{part_id}", print_paths)
    document = Document(width=pt(width), height=pt(height), title="PF idealized curve-hole sample", metadata={"unit": "mm", "prototype": True, "part_id": part_id, "source_input": "samples/idealized_input/input.json"}, artboards=[Artboard(id="artboard.small", name=part_id, left=0, top=pt(height), width=pt(width), height=pt(height))], layers=[layer("layer.cut", "PF_CUT", [cut_group]), layer("layer.print", "PF_PRINT_FRONT", [print_group]), layer("layer.annotation", "PF_ANNOTATION", []), layer("layer.fold", "PF_FOLD", [])])
    document = apply_input_coordinate_system(document, height)
    return Sample("curve-hole", document, ProductionContract(production_id="curve-hole-input", width=pt(width), height=pt(height), layer_names=("PF_CUT", "PF_PRINT_FRONT", "PF_ANNOTATION", "PF_FOLD"), path_count=6, text_count=0, group_count=2, required_ids=("group.cut." + part_id, "group.print." + part_id, "cut." + part_id + ".outer", "cut." + part_id + ".hole.01", "print." + part_id + ".orientation"), required_group_names=(f"PF_PART_{part_id}",), visual_acceptance=("240 × 160 mmの外周は4つのR20 Bézier角を持つ", "中央のφ24穴が切断線と印刷の位置証跡で一致する", "左上原点・+Y下の矢印と左のシアン帯で表面方向と鏡映が識別できる"), artboards=(ProductionArtboard(id="artboard.small", name=part_id, left=0, top=pt(height), width=pt(width), height=pt(height), group_id="group.cut." + part_id, required_ids=("cut." + part_id + ".outer", "cut." + part_id + ".hole.01")),)))


def shelf_sample(data: dict) -> Sample:
    spec = data["shelf_assembly"]
    parts = spec["parts_mm"]
    part_ids = spec["part_ids"]
    gap, columns = 40.0, 2
    positions: dict[str, tuple[float, float]] = {}
    x = y = gap
    row_height = 0.0
    for index, part_id in enumerate(part_ids):
        width, height = map(float, parts[part_id])
        if index and index % columns == 0:
            x = gap
            y += row_height + gap
            row_height = 0.0
        positions[part_id] = (x, y)
        x += width + gap
        row_height = max(row_height, height)
    canvas_width, canvas_height = 800.0, y + row_height + gap
    cut_groups, print_groups = [], []
    for part_id in part_ids:
        width, height = map(float, parts[part_id])
        x, y = positions[part_id]
        contour = rectangle(f"cut.{part_id}.outer", width, height, fill=None, name=f"CUT outer contour {part_id}", x_mm=x, y_mm=y)
        cut_paths = [contour]
        if part_id == "BACK":
            for number, center in enumerate(spec["back_holes"]["centers_mm"], start=1):
                cx, cy = map(float, center)
                cut_paths.append(ellipse(f"cut.BACK.hole.{number:02d}", (x + cx, y + cy), float(spec["back_holes"]["diameter_mm"]), stroke=CUT, fill=None, name=f"CUT BACK hole {number}"))
        cut_groups.append(group(f"group.cut.{part_id}", f"PF_PART_{part_id}", cut_paths))
        print_paths = [rectangle(f"print.{part_id}.base", width, height, fill=PAPER, name=f"print base {part_id}", x_mm=x, y_mm=y), rectangle(f"print.{part_id}.orientation-bar", min(18, width / 8), height, fill=CYAN, name=f"left orientation bar {part_id}", x_mm=x, y_mm=y), arrow(f"print.{part_id}.orientation", x + width - 46, y + height - 70)]
        print_groups.append(group(f"group.print.{part_id}", f"PF_PART_{part_id}", print_paths))
    document = Document(width=pt(canvas_width), height=pt(canvas_height), title="PF idealized 3-shelf multi-part input", metadata={"unit": "mm", "prototype": True, "part_ids": part_ids, "thickness_mm": data["material"]["thickness_mm"], "source_input": "samples/idealized_input/input.json"}, artboards=[Artboard(id="artboard.shelf", name="THREE_SHELF_ASSEMBLY", left=0, top=pt(canvas_height), width=pt(canvas_width), height=pt(canvas_height))], layers=[layer("layer.cut", "PF_CUT", cut_groups), layer("layer.print", "PF_PRINT_FRONT", print_groups), layer("layer.annotation", "PF_ANNOTATION", []), layer("layer.fold", "PF_FOLD", [])])
    document = apply_input_coordinate_system(document, canvas_height)
    required = tuple(f"group.{kind}.{part_id}" for kind in ("cut", "print") for part_id in part_ids)
    return Sample("three-shelf", document, ProductionContract(production_id="three-shelf-input", width=pt(canvas_width), height=pt(canvas_height), layer_names=("PF_CUT", "PF_PRINT_FRONT", "PF_ANNOTATION", "PF_FOLD"), path_count=9 + len(part_ids) * 3, text_count=0, group_count=len(part_ids) * 2, required_ids=required + ("cut.BACK.hole.01", "cut.BACK.hole.02"), required_group_names=tuple(f"PF_PART_{part_id}" for part_id in part_ids), visual_acceptance=("PF_CUTとPF_PRINT_FRONTに同名の7部材グループがある", "左・右側面、3枚の棚、背面、トップボードの寸法が明示入力と一致する", "背面の2つのφ24穴と全ての部材の非対称な向きマーカーが読める"), artboards=(ProductionArtboard(id="artboard.shelf", name="THREE_SHELF_ASSEMBLY", left=0, top=pt(canvas_height), width=pt(canvas_width), height=pt(canvas_height), group_id="group.cut.SIDE_LEFT", required_ids=("cut.SIDE_LEFT.outer",)),)))


def load_data() -> dict:
    data = json.loads(INPUT.read_text(encoding="utf-8"))
    if data.get("unit") != "mm" or data.get("status") != "idealized-prototype-not-production-specification":
        raise ValueError("input.json must declare the draft millimetre prototype status")
    if data["material"]["thickness_mm"] <= 0:
        raise ValueError("material thickness must be positive")
    return data


def validation_evidence(data: dict, samples: list[Sample]) -> dict:
    """Record the input-to-editable-IR invariants required before later export work."""

    small, shelf = samples
    small_spec = data["small_sample"]
    shelf_spec = data["shelf_assembly"]
    small_cut = small.document.layers[0].groups[0].paths
    shelf_cut_groups = shelf.document.layers[0].groups
    shelf_print_groups = shelf.document.layers[1].groups
    expected_part_ids = shelf_spec["part_ids"]
    checks = {
        "draft_status_and_mm_unit": data["status"] == "idealized-prototype-not-production-specification" and data["unit"] == "mm",
        "positive_explicit_thickness_mm": math.isclose(data["material"]["thickness_mm"], 3.0),
        "small_outer_is_closed_true_bezier": small_cut[0].closed and len(small_cut[0].points) == 8 and all(point.smooth and point.in_handle and point.out_handle for point in small_cut[0].points),
        "small_outer_dimensions_mm": math.isclose(max(point.x for point in small_cut[0].points) / MM_TO_PT, small_spec["width_mm"]) and math.isclose(max(point.y for point in small_cut[0].points) / MM_TO_PT, small_spec["height_mm"]),
        "small_hole_is_closed_phi24": small_cut[1].closed and len(small_cut[1].points) == 4 and math.isclose((max(point.x for point in small_cut[1].points) - min(point.x for point in small_cut[1].points)) / MM_TO_PT, small_spec["hole_diameter_mm"]),
        "matching_part_groups_on_cut_and_print": [item.name for item in shelf_cut_groups] == [f"PF_PART_{part_id}" for part_id in expected_part_ids] == [item.name for item in shelf_print_groups],
        "shelf_dimensions_match_explicit_mm": all(math.isclose((group.paths[0].points[1].x - group.paths[0].points[0].x) / MM_TO_PT, shelf_spec["parts_mm"][part_id][0]) and math.isclose(abs(group.paths[0].points[2].y - group.paths[0].points[1].y) / MM_TO_PT, shelf_spec["parts_mm"][part_id][1]) for group, part_id in zip(shelf_cut_groups, expected_part_ids, strict=True)),
        "back_has_two_closed_phi24_holes": len(shelf_cut_groups[5].paths) == 3 and all(path.closed and len(path.points) == 4 and math.isclose((max(point.x for point in path.points) - min(point.x for point in path.points)) / MM_TO_PT, shelf_spec["back_holes"]["diameter_mm"]) for path in shelf_cut_groups[5].paths[1:]),
        "every_part_has_asymmetric_front_marker": all(len(group.paths) == 3 and group.paths[1].name and "orientation bar" in group.paths[1].name and group.paths[2].name == "FRONT +Y orientation arrow" for group in shelf_print_groups),
        "top_left_y_down_maps_to_illustrator_y_up": math.isclose(max(point.y for point in small_cut[0].points), pt(small_spec["height_mm"])) and math.isclose(min(point.y for point in small_cut[0].points), 0.0) and shelf.document.layers[1].groups[0].paths[2].points[4].y < shelf.document.layers[1].groups[0].paths[2].points[0].y,
    }
    return {"status": "passed" if all(checks.values()) else "failed", "checks": checks}


def generate(output: Path, *, force: bool) -> list[dict]:
    data = load_data()
    samples = [small_sample(data), shelf_sample(data)]
    output.mkdir(parents=True, exist_ok=True)
    validation = validation_evidence(data, samples)
    if validation["status"] != "passed":
        raise RuntimeError(f"input structure validation failed: {validation['checks']}")
    reports = []
    for sample in samples:
        pure = verify_reference_document(lambda document=sample.document: document, contract=sample.contract)
        if pure["status"] != "passed":
            raise RuntimeError(f"pure gate failed for {sample.key}: {pure['checks']}")
        target = output / sample.key
        report = compile_reference_production(lambda document=sample.document: document, source=SOURCE, input_data=INPUT, output_directory=target, contract=sample.contract, force=force, timeout=120)
        reports.append({"sample": sample.key, "report": report})
    (output / "summary.json").write_text(json.dumps({"source": str(SOURCE), "input": str(INPUT), "input_structure_validation": validation, "reports": reports}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return reports


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    reports = generate(args.output_dir.resolve(), force=args.force)
    print(json.dumps({"statuses": {entry["sample"]: entry["report"]["status"] for entry in reports}}, ensure_ascii=False))
    return 0 if all(entry["report"]["status"] == "awaiting-visual-acceptance" for entry in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
