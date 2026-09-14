"""Pure contract tests for the note-free native Illustrator exporter."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


_SOURCE = Path(__file__).parents[1] / "tools" / "export_illustrator.py"
_SPEC = importlib.util.spec_from_file_location("export_illustrator", _SOURCE)
assert _SPEC and _SPEC.loader
exporter = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(exporter)


def _path(name: str, anchors: list[list[float]], *, layer: str, closed: bool = True, filled: bool = False, part: str = "PANEL") -> dict:
    return {
        "name": name, "closed": closed, "filled": filled, "stroked": not filled,
        "parent": {"type": "GroupItem", "name": f"PF_PART_{part}"}, "stroke_width": 1.0,
        "anchors": [{"anchor": point, "left_direction": point, "right_direction": point,
                     "point_type": "PointType.CORNER"} for point in anchors],
        "layer": layer,
    }


def _dom(paths: list[dict]) -> dict:
    group_layers = {}
    group_entries = []
    seen_groups = set()
    for path in paths:
        group_layers[f"{path['layer']}:{path['parent']['name']}"] = path["layer"]
        marker = (path["layer"], path["parent"]["name"])
        if marker not in seen_groups:
            group_entries.append({"name": path["parent"]["name"], "layer": path["layer"]})
            seen_groups.add(marker)
        path.setdefault("ancestor_groups", [{"name": path["parent"]["name"]}])
        for group in path["ancestor_groups"]:
            name = group.get("name") if isinstance(group, dict) else None
            ancestor_marker = (path["layer"], name)
            if isinstance(name, str) and name.startswith("PF_PART_") and ancestor_marker not in seen_groups:
                group_layers[f"{path['layer']}:{name}"] = path["layer"]
                group_entries.append({"name": name, "layer": path["layer"]})
                seen_groups.add(ancestor_marker)
    return {"illustrator": {"ok": True, "layer_names": ["PF_CUT", "PF_PRINT_FRONT", "PF_FOLD", "PF_ANNOTATION"],
            "artboards": [{"rect": [0, 72, 144, 0]}], "group_layers": group_layers,
            "group_entries": group_entries, "paths": paths}}


class ExportFromDomTests(unittest.TestCase):
    def test_classifies_hole_inside_curve_but_outside_anchor_chord(self) -> None:
        outer = _path("curve", [[0, 36], [36, 72], [72, 36], [36, 0]], layer="PF_CUT")
        handles = [([0, 16.1], [0, 55.9]), ([16.1, 72], [55.9, 72]), ([72, 55.9], [72, 16.1]), ([55.9, 0], [16.1, 0])]
        for point, (left, right) in zip(outer["anchors"], handles): point["left_direction"], point["right_direction"] = left, right
        hole = _path("hole", [[17, 66], [23, 66], [23, 60], [17, 60]], layer="PF_CUT")
        result = exporter.export_from_dom(_dom([outer, hole]), source=_SOURCE, material=None)
        self.assertEqual(len(result["parts"][0]["cut"]["holes"]), 1)
    def test_extracts_note_free_outer_hole_and_fold(self) -> None:
        result = exporter.export_from_dom(_dom([
            _path("cut outline", [[0, 72], [144, 72], [144, 0], [0, 0]], layer="PF_CUT"),
            _path("hole", [[36, 54], [54, 54], [54, 36], [36, 36]], layer="PF_CUT"),
            _path("front artwork", [[0, 72], [144, 72], [144, 0], [0, 0]], layer="PF_PRINT_FRONT", filled=True),
            _path("FOLD_CENTER", [[72, 72], [72, 0]], layer="PF_FOLD", closed=False),
        ]), source=_SOURCE, material={"thickness_mm": 3})
        panel = result["parts"][0]
        self.assertEqual(panel["dimensions_mm"], [50.8, 25.4])
        self.assertEqual(panel["cut"]["outer"]["points"][0]["anchor_mm"], [0.0, 0.0])
        self.assertEqual(len(panel["cut"]["holes"]), 1)
        self.assertEqual(panel["folds"][0]["id"], "FOLD_CENTER")
        self.assertEqual(panel["folds"][0]["endpoints_mm"], [[25.4, 0.0], [25.4, 25.4]])
        self.assertEqual(result["material"]["thickness_mm"], 3.0)

    def test_rejects_ambiguous_cut_contours_without_notes(self) -> None:
        paths = [
            _path("left", [[0, 72], [60, 72], [60, 0], [0, 0]], layer="PF_CUT"),
            _path("right", [[80, 72], [144, 72], [144, 0], [80, 0]], layer="PF_CUT"),
        ]
        with self.assertRaisesRegex(exporter.ExportValidationError, "unambiguous outer"):
            exporter.export_from_dom(_dom(paths), source=_SOURCE, material=None)

    def test_rejects_intersecting_outer_and_overlapping_holes(self) -> None:
        outer = _path("outer", [[0, 72], [144, 72], [144, 0], [0, 0]], layer="PF_CUT")
        crossing = _path("crossing", [[100, 60], [180, 60], [180, 10], [100, 10]], layer="PF_CUT")
        with self.assertRaisesRegex(exporter.ExportValidationError, "intersect or touch"):
            exporter.export_from_dom(_dom([outer, crossing]), source=_SOURCE, material=None)
        hole_a = _path("hole-a", [[20, 60], [80, 60], [80, 20], [20, 20]], layer="PF_CUT")
        hole_b = _path("hole-b", [[60, 50], [120, 50], [120, 10], [60, 10]], layer="PF_CUT")
        with self.assertRaisesRegex(exporter.ExportValidationError, "intersect or touch"):
            exporter.export_from_dom(_dom([outer, hole_a, hole_b]), source=_SOURCE, material=None)

    def test_rejects_pf_layer_path_outside_part_group(self) -> None:
        path = _path("orphan", [[0, 72], [144, 72], [144, 0]], layer="PF_CUT")
        path["parent"] = {"type": "Layer", "name": "PF_CUT"}
        with self.assertRaisesRegex(exporter.ExportValidationError, "PF_PART"):
            exporter.export_from_dom(_dom([path]), source=_SOURCE, material=None)

    def test_rejects_nested_cut_and_non_part_cut_groups_even_with_valid_part(self) -> None:
        valid = _path("valid", [[0, 72], [144, 72], [144, 0], [0, 0]], layer="PF_CUT")
        nested = _path("nested", [[160, 72], [200, 72], [200, 0], [160, 0]], layer="PF_CUT")
        nested["parent"] = {"type": "GroupItem", "name": "PF_PART_BODY"}
        dom = _dom([valid, nested])
        dom["illustrator"]["group_layers"].pop("PF_CUT:PF_PART_BODY")
        with self.assertRaisesRegex(exporter.ExportValidationError, "directly on its PF layer"):
            exporter.export_from_dom(dom, source=_SOURCE, material=None)
        other = _path("other", [[160, 72], [200, 72], [200, 0], [160, 0]], layer="PF_CUT")
        other["parent"] = {"type": "GroupItem", "name": "working"}
        with self.assertRaisesRegex(exporter.ExportValidationError, "non-PF_PART"):
            exporter.export_from_dom(_dom([valid, other]), source=_SOURCE, material=None)

    def test_rejects_duplicate_groups_and_print_only_part(self) -> None:
        cut = _path("cut", [[0, 72], [144, 72], [144, 0], [0, 0]], layer="PF_CUT")
        dom = _dom([cut])
        dom["illustrator"]["group_entries"].append({"name": "PF_PART_PANEL", "layer": "PF_CUT"})
        with self.assertRaisesRegex(exporter.ExportValidationError, "duplicate part group"):
            exporter.export_from_dom(dom, source=_SOURCE, material=None)
        print_only = _path("print", [[0, 72], [20, 72], [20, 0], [0, 0]], layer="PF_PRINT_FRONT", part="PRINT_ONLY")
        with self.assertRaisesRegex(exporter.ExportValidationError, "without PF_CUT"):
            exporter.export_from_dom(_dom([cut, print_only]), source=_SOURCE, material=None)

    def test_allows_compound_print_path_without_cut_path_rules(self) -> None:
        cut = _path("cut", [[0, 72], [144, 72], [144, 0], [0, 0]], layer="PF_CUT")
        compound = _path("outlined text", [[10, 20], [20, 20], [20, 10]], layer="PF_PRINT_FRONT")
        compound["parent"] = {"type": "CompoundPathItem", "name": ""}
        compound["ancestor_groups"] = [{"name": "PF_PART_PANEL"}]
        result = exporter.export_from_dom(_dom([cut, compound]), source=_SOURCE, material=None)
        self.assertEqual(result["parts"][0]["print_front"]["paths"], [])

    def test_rejects_compound_print_outside_part_group(self) -> None:
        cut = _path("cut", [[0, 72], [144, 72], [144, 0], [0, 0]], layer="PF_CUT")
        compound = _path("orphan compound", [[10, 20], [20, 20], [20, 10]], layer="PF_PRINT_FRONT")
        compound["parent"] = {"type": "CompoundPathItem", "name": ""}
        compound["ancestor_groups"] = []
        with self.assertRaisesRegex(exporter.ExportValidationError, "inside a PF_PART"):
            exporter.export_from_dom(_dom([cut, compound]), source=_SOURCE, material=None)

    def test_rejects_open_cut_and_nonstraight_fold(self) -> None:
        open_cut = _path("cut", [[0, 72], [144, 72], [144, 0]], layer="PF_CUT", closed=False)
        with self.assertRaisesRegex(exporter.ExportValidationError, "closed"):
            exporter.export_from_dom(_dom([open_cut]), source=_SOURCE, material=None)
        paths = [_path("cut", [[0, 72], [144, 72], [144, 0], [0, 0]], layer="PF_CUT"),
                 _path("FOLD_BAD", [[20, 72], [80, 0]], layer="PF_FOLD", closed=False)]
        paths[1]["anchors"][0]["right_direction"] = [30, 50]
        with self.assertRaisesRegex(exporter.ExportValidationError, "straight"):
            exporter.export_from_dom(_dom(paths), source=_SOURCE, material=None)

    def test_ignores_annotation_and_accepts_missing_vector_print_paths(self) -> None:
        paths = [
            _path("cut", [[0, 72], [144, 72], [144, 0], [0, 0]], layer="PF_CUT"),
            _path("dimension", [[0, 70], [144, 70]], layer="PF_ANNOTATION", closed=False),
        ]
        result = exporter.export_from_dom(_dom(paths), source=_SOURCE, material=None)
        self.assertEqual(result["parts"][0]["print_front"]["paths"], [])
        self.assertEqual(result["material"]["status"], "missing")


if __name__ == "__main__":
    unittest.main()
