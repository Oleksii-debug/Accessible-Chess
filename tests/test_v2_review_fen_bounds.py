from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from acs.input_limits import MAX_FEN_CHARS
from acs.version2_release_ui import Version2ReleaseAccessibleChessAPI


class _HostileFen(str):
    armed = False
    touched = False

    @classmethod
    def reset(cls):
        cls.armed = False
        cls.touched = False

    @classmethod
    def _touch(cls):
        if cls.armed:
            cls.touched = True
            raise AssertionError("hostile FEN text hook must not execute")

    def __len__(self):
        type(self)._touch()
        return super().__len__()

    def strip(self, *args, **kwargs):
        type(self)._touch()
        return super().strip(*args, **kwargs)

    def __str__(self):
        type(self)._touch()
        return super().__str__()


class Version2ReviewFenBoundsTests(unittest.TestCase):
    def make_api(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        return Version2ReleaseAccessibleChessAPI(
            keymap_path=Path(temp.name) / "keymap.json"
        )

    def test_hostile_text_subclass_rejects_before_length_strip_or_parse(self):
        api = self.make_api()
        _HostileFen.reset()
        value = _HostileFen(api.start_fen)
        _HostileFen.armed = True

        with patch("acs.version2_release_ui.Board") as board:
            result = api.project_review_fen(value)

        self.assertEqual(result, {"ok": False})
        self.assertFalse(_HostileFen.touched)
        board.assert_not_called()
        self.assertIsNone(api._external_review_fen)

    def test_over_limit_raw_fen_rejects_before_normalization_or_board_parse(self):
        api = self.make_api()
        oversized = " " * (MAX_FEN_CHARS + 1)

        with patch("acs.version2_release_ui.Board") as board:
            result = api.project_review_fen(oversized)

        self.assertEqual(result, {"ok": False})
        board.assert_not_called()
        self.assertIsNone(api._external_review_fen)

    def test_rejected_oversized_review_does_not_replace_prior_projection(self):
        api = self.make_api()
        accepted = api.project_review_fen(api.start_fen)
        self.assertEqual(accepted, {"ok": True})
        prior = api._external_review_fen

        rejected = api.project_review_fen("x" * (MAX_FEN_CHARS + 1))

        self.assertEqual(rejected, {"ok": False})
        self.assertEqual(api._external_review_fen, prior)

    def test_exact_valid_fen_with_outer_space_still_projects_canonically(self):
        api = self.make_api()

        result = api.project_review_fen("  " + api.start_fen + "  ")

        self.assertEqual(result, {"ok": True})
        self.assertEqual(api._external_review_fen, api.start_fen)

    def test_exact_malformed_within_budget_remains_fail_closed(self):
        api = self.make_api()

        result = api.project_review_fen("not-a-fen")

        self.assertEqual(result, {"ok": False})
        self.assertIsNone(api._external_review_fen)


if __name__ == "__main__":
    unittest.main()
