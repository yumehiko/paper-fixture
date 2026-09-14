import copy
import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.assembly_input import evaluate_checks, load_placement, matrix_4x4, validate_placement
from tools.panel_input import InputError


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "samples/placement/three-shelf-placement.json"


class AssemblyInputTests(unittest.TestCase):
    def payload(self):
        return json.loads(FIXTURE.read_text())

    def test_seven_part_fixture_resolves_matrices_aabbs_and_generic_reference_faces(self):
        resolved = load_placement(FIXTURE, ROOT)
        report = evaluate_checks(resolved)
        by_id = {instance["id"]: instance for instance in resolved["instances"]}
        self.assertEqual(len(by_id), 7)
        self.assertEqual(by_id["shelf-01"]["matrix_mm"][2][3], 118.5)
        self.assertEqual(by_id["shelf-02"]["matrix_mm"][2][3], 238.5)
        self.assertEqual(by_id["shelf-03"]["matrix_mm"][2][3], 358.5)
        self.assertAlmostEqual(by_id["side-left"]["world_aabb_mm"]["x"][0], -3.0)
        self.assertAlmostEqual(by_id["side-left"]["world_aabb_mm"]["z"][0], 0.0)
        self.assertTrue(all(item["passed"] for item in report["expected_checks"]))
        self.assertTrue(all(item["passed"] for item in report["expected_contacts"]))

    def test_same_part_multiple_instances_and_non_axis_aligned_rotation_are_valid_without_contact(self):
        payload = self.payload()
        payload["instances"] = [
            {"id": "repeat-a", "part_id": "SHELF_01", "translation_mm": [10, 20, 30], "rotation_deg_xyz": [0, 0, 0]},
            {"id": "repeat-b", "part_id": "SHELF_01", "translation_mm": [40, 50, 60], "rotation_deg_xyz": [17, 23, 31]},
        ]
        payload["checks"] = {}
        resolved = validate_placement(payload, ROOT)
        self.assertEqual([item["part_id"] for item in resolved["instances"]], ["SHELF_01", "SHELF_01"])
        self.assertNotAlmostEqual(resolved["instances"][1]["matrix_mm"][0][1], 0.0)
        self.assertEqual(evaluate_checks(resolved), {"expected_checks": [], "expected_contacts": []})

    def test_xyz_extrinsic_rotation_has_fixed_world_axis_matrix(self):
        matrix = matrix_4x4([0, 0, 0], [90, 0, -90])
        self.assertAlmostEqual(matrix[0][0], 0.0, places=12)
        self.assertAlmostEqual(matrix[1][0], -1.0, places=12)
        self.assertAlmostEqual(matrix[2][1], 1.0, places=12)
        self.assertAlmostEqual(matrix[0][2], -1.0, places=12)

    def test_rejects_unknown_part_duplicate_id_nonfinite_scale_unknown_field_and_bad_rotation_contract(self):
        cases = []
        unknown_part = self.payload()
        unknown_part["instances"][0]["part_id"] = "MISSING"
        cases.append((unknown_part, "part_id is unknown"))
        duplicate = self.payload()
        duplicate["instances"][1]["id"] = duplicate["instances"][0]["id"]
        cases.append((duplicate, "is duplicated"))
        nonfinite = self.payload()
        nonfinite["instances"][0]["translation_mm"][0] = math.inf
        cases.append((nonfinite, "finite number"))
        scale = self.payload()
        scale["instances"][0]["scale"] = [1, 1, 1]
        cases.append((scale, "scale is unknown"))
        bad_rotation = self.payload()
        bad_rotation["world"]["rotation_mode"] = "XYZ intrinsic degrees"
        cases.append((bad_rotation, "rotation_mode"))
        for payload, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(InputError, message):
                    validate_placement(payload, ROOT)

    def test_rejects_bad_contact_and_reports_inapplicable_contact_separately(self):
        invalid = self.payload()
        invalid["checks"]["expected_contacts"][0]["b_face"] = "min_y"
        with self.assertRaisesRegex(InputError, "opposite faces on one axis"):
            validate_placement(invalid, ROOT)
        rotated = self.payload()
        rotated["instances"][0]["rotation_deg_xyz"] = [17, 0, 0]
        with self.assertRaisesRegex(InputError, "not applicable"):
            evaluate_checks(validate_placement(rotated, ROOT))

    def test_contact_gap_keeps_penetration_sign_and_rejects_negative_target(self):
        payload = self.payload()
        payload["instances"][2]["translation_mm"][0] = -1
        with self.assertRaisesRegex(InputError, "not satisfied"):
            evaluate_checks(validate_placement(payload, ROOT))
        payload = self.payload()
        payload["checks"]["expected_contacts"][0]["target_gap_mm"] = -0.1
        with self.assertRaisesRegex(InputError, "target_gap_mm must be non-negative"):
            validate_placement(payload, ROOT)

    def test_cli_returns_nonzero_for_invalid_input_and_writes_resolved_report(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            report = directory / "report.json"
            success = subprocess.run([sys.executable, "tools/verify_assembly_placement.py", "--input", str(FIXTURE), "--repo-root", str(ROOT), "--report", str(report)], cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(success.returncode, 0, success.stderr)
            self.assertEqual(json.loads(report.read_text())["placement"]["instances"][0]["id"], "side-left")
            invalid = self.payload()
            invalid["instances"][0]["scale"] = [1, 1, 1]
            source = directory / "invalid.json"
            source.write_text(json.dumps(invalid))
            failure = subprocess.run([sys.executable, "tools/verify_assembly_placement.py", "--input", str(source), "--repo-root", str(ROOT)], cwd=ROOT, text=True, capture_output=True)
            self.assertNotEqual(failure.returncode, 0)
            self.assertIn("scale is unknown", failure.stderr)
