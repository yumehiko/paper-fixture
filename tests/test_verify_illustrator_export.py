"""Contract tests for colour-independent print isolation verification."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
import zlib
from pathlib import Path


_SOURCE = Path(__file__).parents[1] / "tools" / "verify_illustrator_export.py"
sys.path.insert(0, str(_SOURCE.parent))
_SPEC = importlib.util.spec_from_file_location("verify_illustrator_export", _SOURCE)
assert _SPEC and _SPEC.loader
verifier = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(verifier)


def _png(path: Path, rgba: bytes) -> None:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        import binascii

        return len(payload).to_bytes(4, "big") + kind + payload + binascii.crc32(kind + payload).to_bytes(4, "big")

    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", (1).to_bytes(4, "big") + (1).to_bytes(4, "big") + b"\x08\x06\x00\x00\x00") + chunk(b"IDAT", zlib.compress(b"\x00" + rgba)) + chunk(b"IEND", b""))


def _evidence(pixel_sha256: str) -> dict:
    return {"dom": {"illustrator": {"layer_names": ["PF_CUT", "PF_PRINT_FRONT", "PF_ANNOTATION"]}}, "print_front_png": {"visible_layer": "PF_PRINT_FRONT", "hidden_layers": ["PF_CUT", "PF_ANNOTATION"], "pixel_sha256": pixel_sha256}}


class PrintIsolationTests(unittest.TestCase):
    def test_accepts_a_red_print_pixel(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            delivered, reference = root / "print.png", root / "reference.png"
            _png(delivered, b"\xff\x00\x00\xff")
            _png(reference, b"\xff\x00\x00\xff")
            digest = verifier.hashlib.sha256(b"\xff\x00\x00\xff").hexdigest()
            result = verifier._verify_print_isolation(_evidence(digest), delivered, reference)
        self.assertTrue(result["passed"])
        self.assertEqual(result["fresh_print_only_reexport"], "matched")

    def test_rejects_cut_layer_pixel_even_when_not_red(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            delivered, reference = root / "print.png", root / "reference.png"
            _png(delivered, b"\x00\xff\x00\xff")
            _png(reference, b"\xff\x00\x00\xff")
            digest = verifier.hashlib.sha256(b"\x00\xff\x00\xff").hexdigest()
            result = verifier._verify_print_isolation(_evidence(digest), delivered, reference)
        self.assertFalse(result["passed"])
        self.assertEqual(result["fresh_print_only_reexport"], "mismatched")
