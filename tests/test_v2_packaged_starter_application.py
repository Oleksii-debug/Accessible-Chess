from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.version2_packaged_starter_application import Version2PackagedStarterApplication


_STARTER_PGN = """[Event \"Starter sample\"]
[Site \"Offline\"]
[Date \"2026.09.26\"]
[Round \"1\"]
[White \"Student\"]
[Black \"Coach\"]
[Result \"*\"]

1. e4 e5 2. Nf3 Nc6 *
"""

_STRESS_PGN = """[Event \"Stress sample\"]
[Site \"Offline\"]
[Date \"2026.09.26\"]
[Round \"1\"]
[White \"A\"]
[Black \"B\"]
[Result \"*\"]

1. d4 d5 2. c4 e6 *
"""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_bundle(root: Path) -> None:
    root.mkdir(parents=True)
    (root / "starter_uk.pgn").write_text(_STARTER_PGN, encoding="utf-8")
    (root / "stress_uk.pgn").write_text(_STRESS_PGN, encoding="utf-8")
    with AcsDatabase(root / "sample_library.acsdb") as database:
        database.import_pgn_text(_STARTER_PGN, source_name="starter_uk.pgn")
    files = {}
    for name, license_id in (
        ("starter_uk.pgn", "CC0-1.0"),
        ("stress_uk.pgn", "LicenseRef-Accessible-Chess-Starter-Content-1.0"),
        ("sample_library.acsdb", "CC0-1.0"),
    ):
        path = root / name
        files[name] = {
            "sha256": _sha256(path),
            "bytes": path.stat().st_size,
            "license_id": license_id,
        }
    manifest = {
        "schema_version": 3,
        "bundle_kind": "lawful-curated-real-game-starter",
        "runtime_network_required": False,
        "starter_source": {
            "license_id": "CC0-1.0",
            "selected_games": 240,
        },
        "counts": {"starter_games": 240, "stress_games": 1200},
        "files": files,
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )


class PackagedStarterApplicationTests(unittest.TestCase):
    def _application(self, root: Path, bundle: Path):
        database = AcsDatabase(root / "user-library.acsdb")
        analysis = AnalysisService(lambda: None)
        app = Version2PackagedStarterApplication(
            database,
            packaged_starter_root=bundle,
            progress_store=BookProgressStore(root / "book-progress.json"),
            engine_assistance=EngineAssistedWorkflowService(analysis),
            board_dispatch=lambda *_: None,
            board_position_projector=lambda _fen: {"ok": True},
        )
        return app, database, analysis

    def test_packaged_w2_actions_are_discoverable_and_open_through_canonical_pgn(self) -> None:
        with tempfile.TemporaryDirectory(prefix="accessible-chess-p0f-w2-runtime-") as raw:
            root = Path(raw)
            bundle = root / "package" / "release-content" / "w2-starter"
            _write_bundle(bundle)
            app, database, analysis = self._application(root, bundle)
            try:
                library = app.snapshot()["library"]
                starter = library["packaged_starter_content"]
                self.assertTrue(starter["available"])
                self.assertEqual(240, starter["starter_games"])
                self.assertEqual(1200, starter["stress_games"])
                self.assertFalse(starter["network_required"])
                self.assertTrue(starter["prebuilt_library"])

                actions = {item["action"]: item for item in library["actions"]}
                self.assertIn("library.open_packaged_starter_pgn", actions)
                self.assertIn("library.open_packaged_stress_pgn", actions)
                self.assertTrue(actions["library.open_packaged_starter_pgn"]["enabled"])

                result = app.browser_command(
                    "library", "library.open_packaged_starter_pgn", {}
                )
                self.assertEqual("status", result["kind"])
                self.assertEqual("pgn", app.shell.current_route.route_id)
                self.assertIsNotNone(app.session)
                self.assertEqual(1, app.session.view().game_count)
                self.assertTrue(app.session.dirty)
                self.assertIsNone(app.session.view().source_path)

                result = app.browser_command(
                    "library", "library.open_packaged_stress_pgn", {}
                )
                self.assertEqual("status", result["kind"])
                self.assertEqual("pgn", app.shell.current_route.route_id)
                self.assertEqual(1, app.session.view().game_count)
                self.assertTrue(app.session.dirty)
                self.assertIsNone(app.session.view().source_path)
            finally:
                app.shutdown()
                analysis.close()
                database.close()

    def test_tampered_packaged_payload_fails_closed_before_application_start(self) -> None:
        with tempfile.TemporaryDirectory(prefix="accessible-chess-p0f-w2-tamper-") as raw:
            root = Path(raw)
            bundle = root / "w2-starter"
            _write_bundle(bundle)
            with (bundle / "starter_uk.pgn").open("a", encoding="utf-8") as handle:
                handle.write("\n{tampered}\n")
            database = AcsDatabase(root / "user-library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                with self.assertRaisesRegex(RuntimeError, "integrity failed"):
                    Version2PackagedStarterApplication(
                        database,
                        packaged_starter_root=bundle,
                        progress_store=BookProgressStore(root / "book-progress.json"),
                        engine_assistance=EngineAssistedWorkflowService(analysis),
                        board_dispatch=lambda *_: None,
                    )
            finally:
                analysis.close()
                database.close()

    def test_missing_explicit_bundle_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="accessible-chess-p0f-w2-missing-") as raw:
            root = Path(raw)
            database = AcsDatabase(root / "user-library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                with self.assertRaisesRegex(RuntimeError, "root is missing"):
                    Version2PackagedStarterApplication(
                        database,
                        packaged_starter_root=root / "missing",
                        progress_store=BookProgressStore(root / "book-progress.json"),
                        engine_assistance=EngineAssistedWorkflowService(analysis),
                        board_dispatch=lambda *_: None,
                    )
            finally:
                analysis.close()
                database.close()


if __name__ == "__main__":
    unittest.main()
