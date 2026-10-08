"""Fail-closed tests for downloaded CC0 source and optional offline raster derivation."""
from __future__ import annotations
from pathlib import Path
import shutil
import tempfile
import unittest

from tools.revised_section42_render_piece_pack import PiecePackError, qualify_sources

ROOT=Path(__file__).resolve().parents[1]

class Section42RasterQualificationTests(unittest.TestCase):
    def test_all_12_originals_pass_exact_licensing_source_gate(self):
        originals=qualify_sources(ROOT)
        self.assertEqual(len(originals),12)
        self.assertEqual(len({x[0] for x in originals}),12)

    def test_corrupt_or_missing_pieces_are_refused_before_conversion(self):
        with tempfile.TemporaryDirectory(prefix="ac42-source-gate-") as raw:
            root=Path(raw)
            dst=root/"web/assets/pieces/rhosgfx"
            dst.parent.mkdir(parents=True)
            shutil.copytree(ROOT/"web/assets/pieces/rhosgfx",dst)
            victim=dst/"wK.svg"
            victim.write_bytes(victim.read_bytes()+b"\n<!-- modified -->")
            with self.assertRaises(PiecePackError):
                qualify_sources(root)
            shutil.copy2(ROOT/"web/assets/pieces/rhosgfx/wK.svg",victim)
            victim.unlink()
            with self.assertRaises(PiecePackError):
                qualify_sources(root)
            shutil.copy2(ROOT/"web/assets/pieces/rhosgfx/wK.svg",victim)
            self.assertEqual(len(qualify_sources(root)),12)
            victim.unlink()
            try:
                victim.symlink_to(ROOT/"web/assets/pieces/rhosgfx/wK.svg")
            except OSError:  # Unprivileged Windows runner cannot create symlinks.
                return
            with self.assertRaises(PiecePackError):
                qualify_sources(root)

if __name__=="__main__":
    unittest.main()
