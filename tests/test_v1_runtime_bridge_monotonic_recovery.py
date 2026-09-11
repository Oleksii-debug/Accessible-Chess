from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.v1_runtime_bridge import V1RuntimeBridgeCoordinator, V1RuntimeBridgeError
from acs.version2_upgrade import UserDataLayout


_VALID_PGN = """[Event "Legacy"]
[Site "?"]
[Date "2026.01.01"]
[Round "?"]
[White "White"]
[Black "Black"]
[Result "1-0"]

1. e4 e5 2. Nf3 Nc6 1-0
"""


class _InjectedTermination(BaseException):
    """Model an abrupt process exit without Product cleanup."""


class V1RuntimeBridgeMonotonicRecoveryTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, UserDataLayout]:
        install = root / "installed"
        legacy = install / "data"
        legacy.mkdir(parents=True)
        executable = install / "AccessibleChess.exe"
        executable.write_bytes(b"MZ-monotonic-recovery-regression")
        (legacy / "settings.json").write_text(
            json.dumps({"language": "en", "volume": 22}) + "\n",
            encoding="utf-8",
        )
        library = legacy / "library.acsdb"
        connection = sqlite3.connect(library)
        try:
            connection.execute(
                """CREATE TABLE games(
                    id INTEGER PRIMARY KEY,
                    title TEXT,
                    pgn TEXT,
                    created_at TEXT
                )"""
            )
            connection.execute(
                "INSERT INTO games(title,pgn,created_at) VALUES(?,?,?)",
                ("legacy-one.pgn", _VALID_PGN, "2026-01-02T03:04:05+00:00"),
            )
            connection.commit()
        finally:
            connection.close()
        return executable, UserDataLayout(root / "localappdata" / "AccessibleChess")

    @staticmethod
    def _journal_phase(layout: UserDataLayout) -> str | None:
        path = layout.backup_root / ".v1-runtime-bridge-state.json"
        if not path.exists():
            return None
        return str(json.loads(path.read_text(encoding="utf-8"))["phase"])

    def test_newer_library_writer_does_not_regress_library_published_journal(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            executable, layout = self._fixture(Path(td))

            def terminate(phase: str) -> None:
                if phase == "library-published":
                    raise _InjectedTermination("after library publication")

            with self.assertRaises(_InjectedTermination):
                V1RuntimeBridgeCoordinator(
                    layout, executable, phase_hook=terminate
                ).run()

            self.assertEqual(self._journal_phase(layout), "library_published")
            self.assertTrue(layout.settings_path.is_file())
            self.assertTrue(layout.library_path.is_file())

            with AcsDatabase(layout.library_path) as database:
                source_id = database.add_source(
                    "external-writer.pgn", "pgn", "f" * 64
                )
                self.assertGreater(source_id, 0)
            external_library = layout.library_path.read_bytes()
            published_settings = layout.settings_path.read_bytes()

            for _ in range(2):
                with self.assertRaises(V1RuntimeBridgeError):
                    V1RuntimeBridgeCoordinator(layout, executable).run()
                self.assertEqual(layout.library_path.read_bytes(), external_library)
                self.assertEqual(layout.settings_path.read_bytes(), published_settings)
                self.assertEqual(self._journal_phase(layout), "library_published")
                self.assertFalse(
                    (layout.backup_root / ".v1-runtime-bridge-completed.json").exists()
                )


if __name__ == "__main__":
    unittest.main()
