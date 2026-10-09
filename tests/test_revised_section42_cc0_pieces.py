"""Authentic CC0 Lichess art on the canonical accessible board; no source-rule duplication."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import unittest
from acs.visual_board_contract import PieceTheme, VisualBoardPreferences
from acs.webapp import AccessibleChessAPI

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "web/assets/pieces/rhosgfx"
EXPECTED = {c + p + ".svg" for c in "wb" for p in "KQRBNP"}

def blob(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + bytes([0]) + data).hexdigest()

class CC0ChessPieceTests(unittest.TestCase):
    def test_exact_cc0_upstream_art_and_original_license(self):
        m = json.loads((PACK / "SECTION42_PROVENANCE.json").read_text(encoding="utf-8"))
        self.assertEqual(m["license"], "CC0-1.0")
        self.assertEqual(m["upstream_commit"], "f5b261e3d8ece6f511484e398cb8d81e37735bea")
        rights = (PACK / "SOURCE_COPYING.md").read_bytes()
        self.assertEqual(blob(rights), "def9deca8bceae28cf83d2074a3b09534ae88f6f")
        self.assertIn(b"public/piece/rhosgfx", rights)
        self.assertIn(b"CC0 1.0", rights)
        self.assertEqual({a["file"] for a in m["assets"]}, EXPECTED)
        self.assertEqual(len(m["assets"]), 12)
        for a in m["assets"]:
            with self.subTest(piece=a["file"]):
                self.assertEqual(a["upstream_path"], "public/piece/rhosgfx/" + a["file"])
                data = (PACK / a["file"]).read_bytes()
                self.assertEqual(len(data), a["bytes"])
                self.assertEqual(blob(data), a["git_blob_sha1"])
                self.assertIn(b"<svg", data)
                self.assertNotIn(b"<script", data.lower())
                self.assertNotIn(b"<foreignobject", data.lower())

    def test_piece_setting_is_authoritative_and_does_not_modify_game(self):
        self.assertEqual(PieceTheme.RHOSGFX.value, "rhosgfx")
        self.assertEqual(VisualBoardPreferences().updated("piece_theme","rhosgfx").piece_theme, PieceTheme.RHOSGFX)
        self.assertRaises(ValueError, VisualBoardPreferences().updated, "piece_theme", "remote-source")
        api = AccessibleChessAPI("en")
        try:
            initial = api.board.fen()
            tree = api.review_history.export_tree()
            outcome = api.set_visual_preference("piece_theme", "rhosgfx")
            self.assertTrue(outcome["ok"])
            self.assertEqual(outcome["visualBoard"]["preferences"]["pieceTheme"], "rhosgfx")
            self.assertEqual(api.board.fen(), initial)
            self.assertEqual(api.review_history.export_tree(), tree)
            self.assertEqual(len(outcome["visualBoard"]["cells"]), 64)
        finally:
            close = getattr(api,"close_analysis",None)
            if callable(close): close()

    def test_webview_board_keeps_silent_local_images_and_unicode_error_fallback(self):
        ui = (ROOT/"web/index.html").read_text(encoding="utf-8")
        self.assertIn('<option value="rhosgfx">RhosGFX (CC0)</option>',ui)
        self.assertIn("image.src='assets/pieces/rhosgfx/'+safeName",ui)
        self.assertIn("image.addEventListener('error'",ui)
        self.assertIn("image.setAttribute('aria-hidden','true')",ui)
        self.assertIn("node.setAttribute('aria-label',cell.label)",ui)
        self.assertNotIn("localStorage.setItem",ui)
        self.assertIn(".ac42-piece-art",(ROOT/"web/assets/accessible_chess_design.css").read_text(encoding="utf-8"))

    def test_package_preflight_requires_original_hashes_even_if_checksums_rewritten(self):
        preflight=(ROOT/"acs/version2_package_preflight.py").read_text(encoding="utf-8")
        self.assertIn("Section 42 packaged original CC0 artwork altered",preflight)
        self.assertIn("Section 42 CC0 pack incomplete",preflight)
        self.assertIn("original_copying_git_blob_sha1",preflight)

    def test_packaged_windows_fixture_blocks_missing_and_rehashed_tamper(self):
        import tempfile
        from acs.version2_package_preflight import Version2PackagePreflightError
        from tests.test_version2_package_preflight import _make_tree, _write_checksums, _validate_tree

        with tempfile.TemporaryDirectory(prefix="acs-section42-packaging-") as tmp:
            package=Path(tmp)/"candidate"
            package.mkdir()
            _make_tree(package)
            html=package/"AccessibleChess/web/index.html"
            html.write_text(
                '<!doctype html><html><body><select>'
                '<option value="rhosgfx">RhosGFX (CC0)</option>'
                '</select></body></html>', encoding="utf-8",
            )
            _write_checksums(package)
            with self.assertRaises(Version2PackagePreflightError):
                _validate_tree(package)

            for name in ("SECTION42_PROVENANCE.json", "SOURCE_COPYING.md", *sorted(EXPECTED)):
                destination=package/"AccessibleChess/web/assets/pieces/rhosgfx"/name
                destination.parent.mkdir(parents=True,exist_ok=True)
                destination.write_bytes((PACK/name).read_bytes())
            _write_checksums(package)
            _validate_tree(package)

            altered=package/"AccessibleChess/web/assets/pieces/rhosgfx/wK.svg"
            altered.write_bytes(altered.read_bytes()+b"<!-- substituted artwork -->")
            _write_checksums(package)
            with self.assertRaisesRegex(
                Version2PackagePreflightError,
                "Section 42 packaged original CC0 artwork altered",
            ):
                _validate_tree(package)

if __name__ == "__main__":
    unittest.main()
