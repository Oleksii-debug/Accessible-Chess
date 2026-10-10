"""Section 45.5–45.6: cross-surface visual-only transfer, CAS and combination QA."""
from __future__ import annotations

import itertools
import json
from pathlib import Path
import tempfile
import unittest

from acs.settings import Settings
from acs.visual_profile_transfer import (
    FIELDS, VisualProfileTransferError, decode_transfer, encode_transfer,
)
from acs.webapp import AccessibleChessAPI


ROOT = Path(__file__).resolve().parents[1]
DEFAULT = {"profile": "classic", "theme": "system", "board_theme": "wood", "density": "comfortable"}


class Section45TransferMatrixTests(unittest.TestCase):
    def test_all_300_supported_profile_theme_board_density_combinations_roundtrip(self):
        self.assertEqual([len(FIELDS[k]) for k in ("profile", "theme", "board_theme", "density")], [5, 4, 5, 3])
        for profile, theme, board, density in itertools.product(
            sorted(FIELDS["profile"]), sorted(FIELDS["theme"]),
            sorted(FIELDS["board_theme"]), sorted(FIELDS["density"])
        ):
            original = {"profile": profile, "theme": theme, "board_theme": board, "density": density}
            payload = encode_transfer(original)
            self.assertLessEqual(len(payload.encode("utf-8")), 4096)
            self.assertEqual(decode_transfer(payload), original)
            self.assertEqual(encode_transfer(decode_transfer(payload)), payload)

    def test_invalid_version_duplicate_keys_extra_private_fields_and_invalid_json_fail_closed(self):
        valid = encode_transfer(DEFAULT)
        poisoned = [
            valid.replace('"version":1', '"version":2'),
            valid.replace('"version":1', '"version":true'),
            valid.replace('"version":1', '"version":1,"version":1'),
            valid.replace('"theme":"system"', '"theme":"dark","theme":"system"'),
            valid.replace('"theme":"system"', '"theme":"system","password":"secret"'),
            valid.replace('"preferences":', '"private_path":"C:/user","preferences":'),
            valid.replace('"profile":"classic"', '"profile":"__proto__"'),
            valid.replace('"theme":"system"', '"theme":NaN'),
            valid + " trailing",
            "{}",
            "null",
            " " * 4097,
        ]
        for value in poisoned:
            with self.subTest(value=value[:80]):
                with self.assertRaises(VisualProfileTransferError):
                    decode_transfer(value)
        for broken in [None, [], {"theme": "system"}, {**DEFAULT, "student_id": "x"}]:
            with self.assertRaises(VisualProfileTransferError):
                encode_transfer(broken)

    def test_native_import_requires_expected_revision_and_uses_one_settings_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            api = AccessibleChessAPI("en")
            api._settings = Settings(path)
            exported = api.visual_profile_export()
            self.assertTrue(exported["ok"], exported)
            self.assertEqual(decode_transfer(exported["payload"]), DEFAULT)
            target = {**DEFAULT, "theme": "contrast", "board_theme": "high-contrast"}
            payload = encode_transfer(target)
            original_board = api.get_state()
            before = json.loads(api._settings.get("visual_profile_json"))
            self.assertFalse(api.visual_profile_import(payload, "invalid")["ok"])
            self.assertEqual(before, json.loads(api._settings.get("visual_profile_json")))
            result = api.visual_profile_import(payload, exported["revision"])
            self.assertTrue(result["ok"], result)
            self.assertEqual(json.loads(api._settings.get("visual_profile_json")), target)
            # A stale concurrent browser tab must not revert an already-applied choice.
            self.assertEqual(api.visual_profile_import(exported["payload"], exported["revision"])["reason"], "stale_revision")
            self.assertEqual(json.loads(api._settings.get("visual_profile_json")), target)
            self.assertEqual(api.get_state().get("fen"), original_board.get("fen"))
            self.assertEqual(api.get_state().get("moves"), original_board.get("moves"))

            reopened = AccessibleChessAPI("en")
            reopened._settings = Settings(path)
            self.assertEqual(decode_transfer(reopened.visual_profile_export()["payload"]), target)
            self.assertEqual(reopened.visual_profile_get()["board_theme"], "high-contrast")

    def test_invalid_import_never_overwrites_existing_user_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            api = AccessibleChessAPI("uk")
            api._settings = Settings(path)
            initial = api.visual_profile_export()
            self.assertTrue(initial["ok"])
            # Create a real private durable settings file before testing non-mutation.
            self.assertTrue(api.visual_profile_apply("minimal", "light", "minimal", "compact")["ok"])
            before = path.read_bytes()
            rev = api.visual_profile_export()["revision"]
            self.assertFalse(api.visual_profile_import('{"password":"secret"}', rev)["ok"])
            self.assertEqual(path.read_bytes(), before)
            self.assertFalse(api.visual_profile_import(encode_transfer(DEFAULT), initial["revision"])["ok"])
            self.assertEqual(path.read_bytes(), before)

    def test_web_is_explicit_local_transfer_no_hidden_remote_dependency(self):
        html = (ROOT / "web/index.html").read_text(encoding="utf-8")
        js = (ROOT / "web/visual_profile_transfer.js").read_text(encoding="utf-8")
        preflight = (ROOT / "acs/version2_package_preflight.py").read_text(encoding="utf-8")
        for element in ("visual-transfer-export", "visual-transfer-import", "visual-transfer-json",
                        "visual-transfer-status"):
            self.assertIn('id="' + element + '"', html)
        self.assertIn('<script src="visual_profile_transfer.js"></script>', html)
        self.assertIn('"AccessibleChess/web/visual_profile_transfer.js"', preflight)
        for token in ("localStorage", "pywebview", "stale", "visual_profile_import", "visual_profile_export"):
            self.assertIn(token, js)
        for forbidden in ("fetch(", "XMLHttpRequest", "WebSocket", "student_id", "credentials", "document.cookie"):
            self.assertNotIn(forbidden, js)


if __name__ == "__main__":
    unittest.main()
