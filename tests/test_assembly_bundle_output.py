import json
import os
import tempfile
import unittest
from pathlib import Path

from tools.assembly_bundle_output import (
    assert_replaceable, publish_staging, resolve_output_boundary, sha256,
)


class AssemblyBundleOutputTests(unittest.TestCase):
    def input_hashes(self, source):
        return {"placement": {"path": "samples/placement.json", "sha256": source}}

    def write_complete_bundle(self, output, inputs):
        (output / "textures").mkdir(parents=True)
        (output / "textures/print-front.png").write_bytes(b"image")
        manifest = {
            "input_hashes": inputs,
            "output_hashes": {"textures/print-front.png": sha256(output / "textures/print-front.png")},
        }
        (output / "build-manifest.json").write_text(json.dumps(manifest))

    def test_rejects_different_input_even_when_all_previous_outputs_match(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "assembly"
            self.write_complete_bundle(output, self.input_hashes("first"))
            with self.assertRaisesRegex(RuntimeError, "different inputs"):
                assert_replaceable(output, self.input_hashes("second"), force=False)
            assert_replaceable(output, self.input_hashes("second"), force=True)

    def test_rejects_invalid_manifest_types_or_json_and_force_can_recover(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "assembly"
            self.write_complete_bundle(output, self.input_hashes("first"))
            manifest = output / "build-manifest.json"
            for invalid in (
                '{"input_hashes": {}, "output_hashes": []}',
                '{not json',
            ):
                manifest.write_text(invalid)
                with self.assertRaisesRegex(RuntimeError, "manifest is invalid"):
                    assert_replaceable(output, self.input_hashes("first"), force=False)
                # Force is applied only after resolve_output_boundary in the CLI;
                # this helper therefore permits replacing this exact directory.
                assert_replaceable(output, self.input_hashes("first"), force=True)

    def test_rejects_output_that_contains_any_input_or_has_symlink_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            panel = root / "build/source/export.json"
            placement = root / "samples/placement.json"
            image = root / "build/source/print.png"
            for path in (panel, placement, image):
                path.parent.mkdir(parents=True, exist_ok=True); path.write_text("x")
            with self.assertRaisesRegex(RuntimeError, "must not contain an input"):
                resolve_output_boundary(root, root / "build", (placement, panel, image))
            real_parent = Path(directory) / "outside"; real_parent.mkdir()
            linked_parent = root / "build/link"; linked_parent.parent.mkdir(parents=True, exist_ok=True)
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            with self.assertRaisesRegex(RuntimeError, "symlink"):
                resolve_output_boundary(root, linked_parent / "assembly", (placement, panel, image))

    def test_failed_final_replace_restores_previous_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            output, staging = parent / "assembly", parent / "staging"
            output.mkdir(); staging.mkdir()
            (output / "old.txt").write_text("old")
            (staging / "new.txt").write_text("new")
            calls = []

            def fail_second_replace(source, destination):
                calls.append((Path(source), Path(destination)))
                if len(calls) == 2:
                    raise OSError("simulated final replacement failure")
                os.replace(source, destination)

            with self.assertRaisesRegex(OSError, "simulated"):
                publish_staging(staging, output, replace=fail_second_replace)
            self.assertEqual((output / "old.txt").read_text(), "old")
            self.assertFalse((output / "new.txt").exists())
