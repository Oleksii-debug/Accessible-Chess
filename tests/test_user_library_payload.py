from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.user_library_payload import (
    UserLibraryPayloadError,
    load_packaged_user_library,
)
from acs.version2_packaged_starter_application import Version2PackagedStarterApplication
from acs.version2_windows_file_workflows import FileWorkflowEventKind


PGN_ONE = b'[Event "One"]\n[Result "*"]\n\n1. e4 *\n'
PGN_TWO = b'[Event "Two"]\n[Result "*"]\n\n1. d4 *\n'


def _write_user_payload(root: Path, sources: dict[str, bytes]) -> None:
    root.mkdir(parents=True)
    entries = []
    for name, payload in sorted(sources.items(), key=lambda item: item[0].casefold()):
        path = root / name
        path.write_bytes(payload)
        entries.append(
            {
                "name": name,
                "format": "pgn",
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "scope": "owner-private",
                "sources": entries,
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


class UserLibraryPayloadTests(unittest.TestCase):
    def test_verified_owner_private_inventory_is_sorted_and_path_safe(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "user-library"
            _write_user_payload(root, {"b.pgn": PGN_TWO, "a.pgn": PGN_ONE})
            sources = load_packaged_user_library(root)
            self.assertEqual(["a.pgn", "b.pgn"], [source.name for source in sources])
            self.assertTrue(all(source.path.parent == root for source in sources))
            self.assertTrue(all(source.source_format == "pgn" for source in sources))

    def test_tamper_and_undeclared_entries_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "user-library"
            _write_user_payload(root, {"a.pgn": PGN_ONE})
            (root / "a.pgn").write_bytes(PGN_ONE + b"\n{tamper}\n")
            with self.assertRaises(UserLibraryPayloadError):
                load_packaged_user_library(root)

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "user-library"
            _write_user_payload(root, {"a.pgn": PGN_ONE})
            (root / "undeclared.txt").write_text("x", encoding="utf-8")
            with self.assertRaises(UserLibraryPayloadError):
                load_packaged_user_library(root)

    def test_manifest_path_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "user-library"
            root.mkdir()
            payload = PGN_ONE
            (root / "a.pgn").write_bytes(payload)
            (root / "manifest.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "scope": "owner-private",
                        "sources": [
                            {
                                "name": "../a.pgn",
                                "format": "pgn",
                                "bytes": len(payload),
                                "sha256": hashlib.sha256(payload).hexdigest(),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(UserLibraryPayloadError):
                load_packaged_user_library(root)


class _FakeTrustedRuntime:
    def __init__(self) -> None:
        self.import_running = False
        self.started: list[Path] = []

    def start_import_path(self, path):
        if self.import_running:
            raise AssertionError("seed sources must never overlap")
        self.import_running = True
        self.started.append(Path(path))
        return SimpleNamespace(kind=FileWorkflowEventKind.IMPORT_STARTED)

    def shutdown(self, _timeout=None):
        self.import_running = False
        return True


class _EmptyMailbox:
    def drain(self):
        return []


class PackagedUserLibraryQueueTests(unittest.TestCase):
    def test_application_queues_verified_sources_serially_without_exposing_paths(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            user = root / "user-library"
            _write_user_payload(user, {"b.pgn": PGN_TWO, "a.pgn": PGN_ONE})

            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            app = Version2PackagedStarterApplication(
                database,
                packaged_user_library_root=user,
                progress_store=BookProgressStore(root / "book-progress.json"),
                engine_assistance=EngineAssistedWorkflowService(analysis),
                board_dispatch=lambda *_: None,
            )
            runtime = _FakeTrustedRuntime()
            try:
                before = app.snapshot()["library"]["packaged_user_library"]
                self.assertEqual(2, before["sources"])
                self.assertEqual(0, before["processed_sources"])
                self.assertNotIn(str(root), repr(before))

                app.bind_files(runtime)
                self.assertEqual(["a.pgn"], [path.name for path in runtime.started])
                runtime.import_running = False
                app.import_ui_ready(_EmptyMailbox())
                self.assertEqual(
                    ["a.pgn", "b.pgn"],
                    [path.name for path in runtime.started],
                )
                runtime.import_running = False
                app.import_ui_ready(_EmptyMailbox())

                after = app.snapshot()["library"]["packaged_user_library"]
                self.assertEqual(2, after["processed_sources"])
                self.assertEqual(0, after["remaining_sources"])
                self.assertNotIn(str(root), repr(after))
                self.assertTrue(
                    any(
                        "Приватна бібліотека готова" in str(event)
                        or "Owner Library ready" in str(event)
                        for event in app._events
                    )
                )
            finally:
                app.shutdown()
                analysis.close()
                database.close()


if __name__ == "__main__":
    unittest.main()
