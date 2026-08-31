from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from acs.version2_upgrade import (
    UserDataLayout,
    Version2UpgradeCoordinator,
    Version2UpgradeError,
)


class _Crash(BaseException):
    pass


class Version2UpgradeStaleWriterTests(unittest.TestCase):
    def test_external_preserved_file_change_survives_automatic_rollback(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            settings = root / "settings.json"
            original_settings = json.dumps({"language": "en", "volume": 43})
            settings.write_text(original_settings, encoding="utf-8")
            books = root / "books"
            books.mkdir()
            book = books / "lesson.txt"
            book.write_bytes(b"original-book")

            changed = False

            def external_writer(phase: str) -> None:
                nonlocal changed
                if phase == "settings-migrated" and not changed:
                    changed = True
                    book.write_bytes(b"newer-external-book")

            with self.assertRaisesRegex(
                Version2UpgradeError, "original user data was restored"
            ):
                Version2UpgradeCoordinator(
                    UserDataLayout(root), phase_hook=external_writer
                ).run()

            self.assertEqual(book.read_bytes(), b"newer-external-book")
            self.assertEqual(settings.read_text(encoding="utf-8"), original_settings)
            journal = json.loads(
                (root / ".v2-upgrade-state.json").read_text(encoding="utf-8")
            )
            self.assertEqual(journal["phase"], "rolled_back")

    def test_interrupted_recovery_preserves_newer_external_unowned_file(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            (root / "settings.json").write_text(
                json.dumps({"language": "en", "volume": 44}),
                encoding="utf-8",
            )
            books = root / "books"
            books.mkdir()
            book = books / "lesson.txt"
            book.write_bytes(b"original-book")

            def crash(phase: str) -> None:
                if phase == "settings-migrated":
                    raise _Crash()

            with self.assertRaises(_Crash):
                Version2UpgradeCoordinator(
                    UserDataLayout(root), phase_hook=crash
                ).run()

            book.write_bytes(b"newer-after-crash")
            recovered = Version2UpgradeCoordinator(UserDataLayout(root)).run()

            self.assertTrue(recovered.recovered_interrupted_upgrade)
            self.assertEqual(recovered.status, "upgraded")
            self.assertEqual(book.read_bytes(), b"newer-after-crash")


if __name__ == "__main__":
    unittest.main()
