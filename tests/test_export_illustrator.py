"""Pure contract tests for the native Illustrator exporter."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


_SOURCE = Path(__file__).parents[1] / "tools" / "export_illustrator.py"
_SPEC = importlib.util.spec_from_file_location("export_illustrator", _SOURCE)
assert _SPEC and _SPEC.loader
exporter = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(exporter)


def _path(identifier: str, anchors: list[list[float]], *, filled: bool = False) -> dict:
    return {
        "name": identifier,
        "note": 'py-ai-path:{"id":"' + identifier + '"}',
        "closed": True,
        "filled": filled,
        "stroked": not filled,
        "parent": {"type": "GroupItem", "name": "PF_PART_PANEL"},
        "stroke_width": 1.0,
        "anchors": [
            {"anchor": point, "left_direction": point, "right_direction": point, "point_type": "PointType.CORNER"}
            for point in anchors
        ],
    }


def _dom(paths: list[dict]) -> dict:
    return {"illustrator": {"ok": True, "layer_names": ["PF_CUT", "PF_PRINT_FRONT"], "artboards": [{"rect": [0, 72, 144, 0]}], "group_layers": {"PF_CUT:PF_PART_PANEL": "PF_CUT", "PF_PRINT_FRONT:PF_PART_PANEL": "PF_PRINT_FRONT"}, "paths": paths}}


class ExportFromDomTests(unittest.TestCase):
    def test_normalizes_actual_point_space_to_top_left_millimetres(self) -> None:
        result = exporter.export_from_dom(
            _dom([
                _path("cut.PANEL.outer", [[0, 72], [144, 72], [144, 0], [0, 0]]),
                _path("cut.PANEL.hole.01", [[36, 54], [54, 54], [54, 36], [36, 36]]),
                _path("print.PANEL.base", [[0, 72], [144, 72], [144, 0], [0, 0]], filled=True),
            ]),
            source=_SOURCE,
            material={"thickness_mm": 3},
        )
        panel = result["parts"][0]
        self.assertEqual(panel["dimensions_mm"], [50.8, 25.4])
        self.assertEqual(panel["cut"]["outer"]["points"][0]["anchor_mm"], [0.0, 0.0])
        self.assertEqual(panel["cut"]["outer"]["points"][2]["anchor_mm"], [50.8, 25.4])
        self.assertEqual(result["material"]["thickness_mm"], 3.0)

    def test_rejects_missing_part_identifier(self) -> None:
        path = _path("cut.PANEL.outer", [[0, 72], [144, 72], [144, 0], [0, 0]])
        path["note"] = ""
        with self.assertRaisesRegex(exporter.ExportValidationError, "identifier note"):
            exporter.export_from_dom(_dom([path]), source=_SOURCE, material=None)

    def test_rejects_open_or_missing_front_print(self) -> None:
        path = _path("cut.PANEL.outer", [[0, 72], [144, 72], [144, 0], [0, 0]])
        path["closed"] = False
        with self.assertRaisesRegex(exporter.ExportValidationError, "closed"):
            exporter.export_from_dom(_dom([path]), source=_SOURCE, material=None)

    def test_rejects_path_outside_matching_part_group(self) -> None:
        paths = [
            _path("cut.PANEL.outer", [[0, 72], [144, 72], [144, 0], [0, 0]]),
            _path("print.PANEL.base", [[0, 72], [144, 72], [144, 0], [0, 0]], filled=True),
        ]
        paths[1]["parent"] = {"type": "GroupItem", "name": "PF_PART_OTHER"}
        with self.assertRaisesRegex(exporter.ExportValidationError, "PF_PART_PANEL"):
            exporter.export_from_dom(_dom(paths), source=_SOURCE, material=None)

    def test_reports_missing_material_without_inventing_thickness(self) -> None:
        result = exporter.export_from_dom(
            _dom([
                _path("cut.PANEL.outer", [[0, 72], [144, 72], [144, 0], [0, 0]]),
                _path("print.PANEL.base", [[0, 72], [144, 72], [144, 0], [0, 0]], filled=True),
            ]),
            source=_SOURCE,
            material=None,
        )
        self.assertEqual(result["material"]["status"], "missing")


if __name__ == "__main__":
    unittest.main()
