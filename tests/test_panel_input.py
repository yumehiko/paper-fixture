import json
import tempfile
import unittest
from pathlib import Path

from tools.panel_input import InputError, load_bundle, signed_area


ROOT = Path(__file__).resolve().parents[1]
CURVE = ROOT / "build/illustrator-export-r2/curve-hole"


class PanelInputTests(unittest.TestCase):
    def test_real_curve_bundle_is_accepted_and_has_one_hole(self):
        bundle = load_bundle(CURVE / "export.json", CURVE / "print-front.png")
        self.assertEqual(bundle["parts"][0]["id"], "SAMPLE_CURVE_HOLE")
        self.assertEqual(len(bundle["parts"][0]["holes"]), 1)
        self.assertEqual(bundle["thickness_mm"], 3.0)

    def test_rejects_open_outer_contour_without_repairing_it(self):
        payload = json.loads((CURVE / "export.json").read_text())
        payload["parts"][0]["cut"]["outer"]["closed"] = False
        with tempfile.TemporaryDirectory() as directory:
            export = Path(directory) / "export.json"
            export.write_text(json.dumps(payload))
            image = Path(directory) / "print-front.png"
            image.write_bytes(b"fixture")
            with self.assertRaisesRegex(InputError, "closed path"):
                load_bundle(export, image)

    def test_signed_area_distinguishes_winding(self):
        self.assertGreater(signed_area([(0, 0), (1, 0), (0, 1)]), 0)
        self.assertLess(signed_area([(0, 0), (0, 1), (1, 0)]), 0)

    def test_rejects_a_zero_area_cut_path_instead_of_guessing_a_shape(self):
        payload = json.loads((CURVE / "export.json").read_text())
        points = payload["parts"][0]["cut"]["outer"]["points"]
        for point in points:
            point["anchor_mm"][1] = 0
            point["in_handle_mm"][1] = 0
            point["out_handle_mm"][1] = 0
        with tempfile.TemporaryDirectory() as directory:
            export = Path(directory) / "export.json"
            export.write_text(json.dumps(payload))
            image = Path(directory) / "print-front.png"
            image.write_bytes(b"fixture")
            with self.assertRaisesRegex(InputError, "zero signed area"):
                load_bundle(export, image)
