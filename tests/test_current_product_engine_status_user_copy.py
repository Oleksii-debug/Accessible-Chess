from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.stage1_release_ui import Stage1ReleaseAccessibleChessAPI


class CurrentProductEngineStatusUserCopyTests(unittest.TestCase):
    _FORBIDDEN_USER_COPY = (
        "migration",
        "still in progress",
        "перенесення",
        "переноситься",
    )

    def _api(self, lang: str) -> Stage1ReleaseAccessibleChessAPI:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        return Stage1ReleaseAccessibleChessAPI(
            lang=lang,
            keymap_path=Path(self._tmp.name) / "keymap.json",
        )

    def _assert_no_developer_migration_copy(self, payload: dict[str, object]) -> None:
        visible = " ".join(
            str(payload.get(key, ""))
            for key in ("engineStatus", "announcement")
        ).casefold()
        for forbidden in self._FORBIDDEN_USER_COPY:
            self.assertNotIn(forbidden.casefold(), visible)

    def test_shipping_uk_engine_toggle_reports_only_user_state(self) -> None:
        api = self._api("uk")

        enabled = api.toggle_engine()

        self.assertTrue(enabled["ok"])
        self.assertTrue(enabled["engineEnabled"])
        self.assertEqual(enabled["engineStatus"], "Stockfish увімкнено.")
        self.assertEqual(enabled["announcement"], "Аналіз Stockfish увімкнено.")
        self._assert_no_developer_migration_copy(enabled)

        disabled = api.toggle_engine()
        self.assertTrue(disabled["ok"])
        self.assertFalse(disabled["engineEnabled"])
        self.assertEqual(disabled["engineStatus"], "Stockfish вимкнено.")
        self.assertEqual(disabled["announcement"], "Аналіз Stockfish вимкнено.")
        self._assert_no_developer_migration_copy(disabled)

    def test_shipping_en_engine_toggle_reports_only_user_state(self) -> None:
        api = self._api("en")

        enabled = api.toggle_engine()

        self.assertTrue(enabled["ok"])
        self.assertTrue(enabled["engineEnabled"])
        self.assertEqual(enabled["engineStatus"], "Stockfish enabled.")
        self.assertEqual(enabled["announcement"], "Stockfish analysis enabled.")
        self._assert_no_developer_migration_copy(enabled)

        disabled = api.toggle_engine()
        self.assertTrue(disabled["ok"])
        self.assertFalse(disabled["engineEnabled"])
        self.assertEqual(disabled["engineStatus"], "Stockfish disabled.")
        self.assertEqual(disabled["announcement"], "Stockfish analysis disabled.")
        self._assert_no_developer_migration_copy(disabled)


if __name__ == "__main__":
    unittest.main()
