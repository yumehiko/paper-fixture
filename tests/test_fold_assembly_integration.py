"""Blender process regression: two chained folds must yield three real cells."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BLENDER = Path("/Applications/Blender.app/Contents/MacOS/Blender")


def shift_path(path, dx, dy):
    for point in path["points"]:
        for key in ("anchor_mm", "in_handle_mm", "out_handle_mm"):
            point[key][0] += dx
            point[key][1] += dy


class FoldAssemblyIntegrationTests(unittest.TestCase):
    def test_chain_keeps_curve_hole_and_nonzero_bounds(self):
        if not BLENDER.exists():
            self.skipTest("Blender is unavailable")
        with tempfile.TemporaryDirectory(prefix="fold-chain-") as raw:
            repo = Path(raw)
            (repo / "input").mkdir()
            png = ROOT / "build/illustrator-export-r2/curve-hole/print-front.png"
            shutil.copy(png, repo / "input/print.png")
            export = json.loads((ROOT / "build/illustrator-export-r2/curve-hole/export.json").read_text())
            part = export["parts"][0]
            # Translate every source coordinate. This catches local/world hinge
            # confusion while retaining its curved outline and circular hole.
            for path in [part["cut"]["outer"], *part["cut"]["holes"]]:
                shift_path(path, 50, 40)
            part["placement_bounds_mm"] = [50, 40, 290, 200]
            part["folds"] = [
                {"id": "FOLD_01", "endpoints_mm": [[90, 40], [90, 200]]},
                {"id": "FOLD_02", "endpoints_mm": [[230, 40], [230, 200]]},
            ]
            export["print"]["range_mm"] = [50, 40, 290, 200]
            (repo / "input/export.json").write_text(json.dumps(export))
            plan = {"schema": "paper-fixture-fold-plan-v1", "sources": {"export_json": "input/export.json", "print_png": "input/print.png"}, "flat_instances": [{"id":"reference-flat","part_id":part["id"],"transform_mm":[[1,0,0,700],[0,1,0,200],[0,0,1,0],[0,0,0,1]]}], "assemblies": [{"id": "chain", "part_id": part["id"], "root_face": "root", "root_transform_mm": [[0,-1,0,400],[1,0,0,200],[0,0,1,50],[0,0,0,1]], "folds": [
                {"fold_id": "FOLD_01", "parent_face": "root", "child_face": "middle", "child_side": "left", "mountain_valley": "valley", "viewed_from": "print_front", "target_dihedral_deg": 90},
                {"fold_id": "FOLD_02", "parent_face": "middle", "child_face": "tip", "child_side": "left", "mountain_valley": "mountain", "viewed_from": "print_front", "target_dihedral_deg": 120},
            ]}]}
            (repo / "plan.json").write_text(json.dumps(plan))
            output = repo / "out"
            subprocess.run([str(BLENDER), "--background", "--python-exit-code", "1", "--python", str(ROOT / "tools/build_fold_assembly.py"), "--", "--plan", str(repo / "plan.json"), "--repo-root", str(repo), "--output-dir", str(output)], check=True)
            report = repo / "report.json"
            subprocess.run([str(BLENDER), "--background", str(output / "assembly.blend"), "--python-exit-code", "1", "--python", str(ROOT / "tools/verify_fold_assembly.py"), "--", "--bundle", str(output), "--report", str(report)], check=True)
            verified = json.loads(report.read_text())
            self.assertEqual(len(verified["faces"]), 3)
            self.assertEqual(len(verified["roots"]), 1)
            self.assertEqual(verified["roots"][0]["assembly"], "chain")
            self.assertTrue(verified["roots"][0]["root_transform_verified"])
            self.assertLess(verified["roots"][0]["root_transform_max_error"], verified["roots"][0]["root_transform_tolerance"])
            self.assertEqual(verified["flat_instances"], [{"id":"reference-flat","part_id":part["id"],"editable_mesh":True}])
            self.assertEqual({item["fold_id"] for item in verified["folds"]}, {"FOLD_01", "FOLD_02"})
            self.assertTrue(all(item["vertices"] > 8 and item["local_thickness_m"] > 0 for item in verified["faces"]))
            self.assertTrue(all(item["hinge_endpoint_error_m"] < 1e-7 for item in verified["folds"]))
            self.assertTrue(all(item["closed_manifold"] for item in verified["faces"]))
            self.assertEqual(sum(item["holes_open"] for item in verified["faces"]), 1)
            build = json.loads((output / "build-manifest.json").read_text())
            self.assertEqual(set(build["output_hashes"]), {"assembly.blend", "fold-manifest.json", "textures/print-front.png", "verification.json"})
            self.assertEqual(build["input_hashes"]["print_front"]["sha256"], verified["texture_sha256"])
            # The next run must not overwrite an operator-modified bundle.
            (output / "fold-manifest.json").write_text("operator edit")
            with self.assertRaises(subprocess.CalledProcessError):
                subprocess.run([str(BLENDER), "--background", "--python-exit-code", "1", "--python", str(ROOT / "tools/build_fold_assembly.py"), "--", "--plan", str(repo / "plan.json"), "--repo-root", str(repo), "--output-dir", str(output)], check=True)

    def test_single_diagonal_mountain_and_valley(self):
        if not BLENDER.exists():
            self.skipTest("Blender is unavailable")
        with tempfile.TemporaryDirectory(prefix="fold-diagonal-") as raw:
            repo = Path(raw)
            (repo / "input").mkdir()
            shutil.copy(ROOT / "build/illustrator-export-r2/curve-hole/print-front.png", repo / "input/print.png")
            export = json.loads((ROOT / "build/illustrator-export-r2/curve-hole/export.json").read_text())
            part = export["parts"][0]
            # The diagonal avoids the circular cutout, exercising a non-axis
            # hinge while preserving a curved outer boundary and a hole.
            part["folds"] = [{"id": "FOLD_DIAG", "endpoints_mm": [[20, 0], [100, 160]]}]
            (repo / "input/export.json").write_text(json.dumps(export))
            def assembly(name, direction, fold_id="FOLD_DIAG", child_side="right"):
                return {"id": name, "part_id": part["id"], "root_face": "fixed", "folds": [{"fold_id": fold_id, "parent_face": "fixed", "child_face": "moving", "child_side": child_side, "mountain_valley": direction, "viewed_from": "print_front", "target_dihedral_deg": 90}]}
            plan = {"schema": "paper-fixture-fold-plan-v1", "sources": {"export_json": "input/export.json", "print_png": "input/print.png"}, "assemblies": [assembly("diag-valley", "valley"), assembly("diag-mountain", "mountain")]}
            (repo / "plan.json").write_text(json.dumps(plan))
            output, report = repo / "out", repo / "report.json"
            subprocess.run([str(BLENDER), "--background", "--python-exit-code", "1", "--python", str(ROOT / "tools/build_fold_assembly.py"), "--", "--plan", str(repo / "plan.json"), "--repo-root", str(repo), "--output-dir", str(output)], check=True)
            subprocess.run([str(BLENDER), "--background", str(output / "assembly.blend"), "--python-exit-code", "1", "--python", str(ROOT / "tools/verify_fold_assembly.py"), "--", "--bundle", str(output), "--report", str(report)], check=True)
            verified = json.loads(report.read_text())
            self.assertEqual(len(verified["faces"]), 4)
            self.assertEqual(len(verified["folds"]), 2)
            self.assertTrue(all(abs(item["angle_from_flat_deg"] - 90) < .01 for item in verified["folds"]))
            self.assertTrue(all(item["hinge_endpoint_error_m"] < 1e-7 for item in verified["folds"]))
            normal = next(item["child_normal_world"] for item in verified["folds"] if item["assembly"] == "diag-mountain")
            part["folds"] = [{"id": "FOLD_DIAG_REVERSED", "endpoints_mm": [[100, 160], [20, 0]]}]
            (repo / "input/export.json").write_text(json.dumps(export))
            reversed_plan = {"schema": "paper-fixture-fold-plan-v1", "sources": plan["sources"], "assemblies": [assembly("diag-mountain-reversed", "mountain", "FOLD_DIAG_REVERSED", "left")]}
            (repo / "reversed-plan.json").write_text(json.dumps(reversed_plan))
            reversed_output, reversed_report = repo / "out-reversed", repo / "reversed-report.json"
            subprocess.run([str(BLENDER), "--background", "--python-exit-code", "1", "--python", str(ROOT / "tools/build_fold_assembly.py"), "--", "--plan", str(repo / "reversed-plan.json"), "--repo-root", str(repo), "--output-dir", str(reversed_output)], check=True)
            subprocess.run([str(BLENDER), "--background", str(reversed_output / "assembly.blend"), "--python-exit-code", "1", "--python", str(ROOT / "tools/verify_fold_assembly.py"), "--", "--bundle", str(reversed_output), "--report", str(reversed_report)], check=True)
            reversed_normal = json.loads(reversed_report.read_text())["folds"][0]["child_normal_world"]
            self.assertTrue(all(abs(a - b) < 1e-7 for a, b in zip(normal, reversed_normal)))
