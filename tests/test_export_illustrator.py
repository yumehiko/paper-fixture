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
    for path in paths:
        group_layers[f"{path['layer']}:{path['parent']['name']}"] = path["layer"]
    return {"illustrator": {"ok": True, "layer_names": ["PF_CUT", "PF_PRINT_FRONT", "PF_FOLD", "PF_ANNOTATION"],
            "artboards": [{"rect": [0, 72, 144, 0]}], "group_layers": group_layers,
            "paths": paths}}


class ExportFromDomTests(unittest.TestCase):
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
