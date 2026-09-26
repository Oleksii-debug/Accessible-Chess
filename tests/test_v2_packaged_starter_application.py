from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.pgn_document import PgnDocumentError, PgnDocumentErrorCode
from acs.version2_packaged_starter_application import Version2PackagedStarterApplication


_STARTER_COUNT = 200
_STRESS_COUNT = 1200
_PROJECT_LICENSE_ID = "LicenseRef-Accessible-Chess-Starter-Content-1.0"
_CORPUS_NAME = "lichess-standard-rated-2013-01"
_CORPUS_URL = "https://database.lichess.org/standard/lichess_db_standard_rated_2013-01.pgn.zst"
_CORPUS_SHA256 = "aa40b3671fa3cf1072eb182892cd90b0e1e003a4a5943492f64b77e7f3fd1635"
_POLICY_ID = "accessible-chess-p0f-real-sample-v1"
_CURATION_CRITERIA = {
    "minimum_plies": 20,
    "valid_results": ["0-1", "1-0", "1/2-1/2"],
    "required_metadata": ["Event", "White", "Black"],
    "result_minimums": {"1-0": 20, "0-1": 20, "1/2-1/2": 8},
    "length_band_minimums": {"20-59": 20, "60-99": 20, "100+": 8},
    "minimum_distinct_opening_prefixes": 12,
    "opening_prefix_plies": 4,
    "maximum_scanned_games": 5000,
}


def _game_record(index: int, *, event_prefix: str = "Starter sample") -> str:
    return f'''[Event "{event_prefix} {index:03d}"]
[Site "Offline"]
[Date "2026.09.26"]
[Round "{index}"]
[White "Student {index:03d}"]
[Black "Coach {index:03d}"]
[Result "*"]

1. e4 e5 2. Nf3 Nc6 *
'''


def _starter_pgn() -> str:
    return "\n".join(_game_record(index) for index in range(1, _STARTER_COUNT + 1))


def _stress_pgn() -> str:
    return "\n".join(
        _game_record(index, event_prefix="Stress sample")
        for index in range(1, _STRESS_COUNT + 1)
    )


_STRESS_PGN = _stress_pgn()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_bundle(root: Path) -> None:
    root.mkdir(parents=True)
    starter_pgn = _starter_pgn()
    (root / "starter_uk.pgn").write_bytes(starter_pgn.encode("utf-8"))
    (root / "stress_uk.pgn").write_bytes(_STRESS_PGN.encode("utf-8"))
    with AcsDatabase(root / "sample_library.acsdb") as database:
        report = database.import_pgn_text(starter_pgn, source_name="starter_uk.pgn")
        assert len(report.game_ids) == _STARTER_COUNT
    files = {}
    for name, license_id in (
        ("starter_uk.pgn", "CC0-1.0"),
        ("stress_uk.pgn", _PROJECT_LICENSE_ID),
        ("sample_library.acsdb", "CC0-1.0"),
    ):
        path = root / name
        files[name] = {
            "sha256": _sha256(path),
            "bytes": path.stat().st_size,
            "license_id": license_id,
        }
    selected_games = [
        {"record_sha256": hashlib.sha256(_game_record(index).strip().encode("utf-8")).hexdigest()}
        for index in range(1, _STARTER_COUNT + 1)
    ]
    manifest = {
        "schema_version": 3,
        "bundle_kind": "lawful-curated-real-game-starter",
        "runtime_network_required": False,
        "starter_source": {
            "name": _CORPUS_NAME,
            "url": _CORPUS_URL,
            "license_id": "CC0-1.0",
            "published_games": 121_332,
            "compressed_sha256": _CORPUS_SHA256,
            "compressed_bytes": 1,
            "selection": _POLICY_ID,
            "subset_sha256": hashlib.sha256(starter_pgn.encode("utf-8")).hexdigest(),
            "selected_games": _STARTER_COUNT,
            "curation": {
                "policy_id": _POLICY_ID,
                "parser": "acs.pgn_roundtrip.parse_pgn_text(strict=True)",
                "criteria": _CURATION_CRITERIA,
                "selected_games": selected_games,
            },
        },
        "licenses": {
            "CC0-1.0": {"type": "public-domain-dedication"},
            _PROJECT_LICENSE_ID: {"type": "project-owned-redistribution-grant"},
        },
        "counts": {"starter_games": _STARTER_COUNT, "stress_games": _STRESS_COUNT},
        "sample_library": {
            "games": _STARTER_COUNT,
            "distinct_games": _STARTER_COUNT,
            "distinct_player_pairs": _STARTER_COUNT,
            "distinct_events": _STARTER_COUNT,
        },
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
                self.assertEqual(_STARTER_COUNT, starter["starter_games"])
                self.assertEqual(_STRESS_COUNT, starter["stress_games"])
                self.assertFalse(starter["network_required"])
                self.assertTrue(starter["prebuilt_library"])

                actions = {item["action"]: item for item in library["actions"]}
                self.assertIn("library.open_packaged_starter_pgn", actions)
                self.assertIn("library.open_packaged_stress_pgn", actions)
                self.assertIn("library.import_packaged_sample_library", actions)
                self.assertTrue(actions["library.open_packaged_starter_pgn"]["enabled"])
                self.assertIn(str(_STARTER_COUNT), actions["library.open_packaged_starter_pgn"]["label"])
                self.assertIn(str(_STRESS_COUNT), actions["library.open_packaged_stress_pgn"]["label"])
                self.assertIn(str(_STARTER_COUNT), actions["library.import_packaged_sample_library"]["label"])
                self.assertNotIn("240", actions["library.open_packaged_starter_pgn"]["label"])

                result = app.browser_command("library", "library.open_packaged_starter_pgn", {})
                self.assertEqual("status", result["kind"])
                self.assertEqual("pgn", app.shell.current_route.route_id)
                self.assertIsNotNone(app.session)
                self.assertEqual(_STARTER_COUNT, app.session.view().game_count)
                self.assertFalse(app.session.dirty)
                self.assertIsNone(app.session.view().source_path)
                with self.assertRaises(PgnDocumentError) as raised:
                    app.session.save()
                self.assertEqual(PgnDocumentErrorCode.NO_SOURCE, raised.exception.code)

                app.session.edit_tag("Event", "Edited starter sample")
                self.assertTrue(app.session.dirty)
                result = app.browser_command("library", "library.open_packaged_stress_pgn", {})
                self.assertEqual("error", result["kind"])
                self.assertEqual("Edited starter sample", app.session.workspace.games()[0].tags["Event"])
            finally:
                app.shutdown()
                analysis.close()
                database.close()

    def test_clean_packaged_starter_can_switch_to_stress_without_false_unsaved_prompt(self) -> None:
        with tempfile.TemporaryDirectory(prefix="accessible-chess-p0f-w2-clean-switch-") as raw:
            root = Path(raw)
            bundle = root / "w2-starter"
            _write_bundle(bundle)
            app, database, analysis = self._application(root, bundle)
            try:
                first = app.browser_command("library", "library.open_packaged_starter_pgn", {})
                self.assertEqual("status", first["kind"])
                self.assertFalse(app.session.dirty)
                second = app.browser_command("library", "library.open_packaged_stress_pgn", {})
                self.assertEqual("status", second["kind"])
                self.assertFalse(app.session.dirty)
                self.assertIsNone(app.session.view().source_path)
                self.assertEqual(_STRESS_COUNT, app.session.view().game_count)
                self.assertEqual("Stress sample 001", app.session.workspace.games()[0].tags["Event"])
            finally:
                app.shutdown()
                analysis.close()
                database.close()

    def test_manifest_game_count_mismatch_fails_closed_before_pgn_open(self) -> None:
        with tempfile.TemporaryDirectory(prefix="accessible-chess-p0f-w2-count-mismatch-") as raw:
            root = Path(raw)
            bundle = root / "w2-starter"
            _write_bundle(bundle)
            manifest_path = bundle / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["counts"]["stress_games"] = _STRESS_COUNT + 1
            manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            app, database, analysis = self._application(root, bundle)
            try:
                result = app.browser_command("library", "library.open_packaged_stress_pgn", {})
                self.assertEqual("error", result["kind"])
                self.assertIsNone(app.session)
            finally:
                app.shutdown()
                analysis.close()
                database.close()

    def test_manifest_license_drift_fails_closed_before_application_start(self) -> None:
        with tempfile.TemporaryDirectory(prefix="accessible-chess-p0f-w2-license-drift-") as raw:
            root = Path(raw)
            bundle = root / "w2-starter"
            _write_bundle(bundle)
            manifest_path = bundle / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["files"]["starter_uk.pgn"]["license_id"] = _PROJECT_LICENSE_ID
            manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            database = AcsDatabase(root / "user-library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                with self.assertRaisesRegex(RuntimeError, "license failed"):
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

    def test_corpus_identity_drift_fails_closed_before_application_start(self) -> None:
        with tempfile.TemporaryDirectory(prefix="accessible-chess-p0f-w2-source-drift-") as raw:
            root = Path(raw)
            bundle = root / "w2-starter"
            _write_bundle(bundle)
            manifest_path = bundle / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["starter_source"]["compressed_sha256"] = "0" * 64
            manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            database = AcsDatabase(root / "user-library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                with self.assertRaisesRegex(RuntimeError, "compressed_sha256"):
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

    def test_curation_policy_drift_fails_closed_before_application_start(self) -> None:
        with tempfile.TemporaryDirectory(prefix="accessible-chess-p0f-w2-policy-drift-") as raw:
            root = Path(raw)
            bundle = root / "w2-starter"
            _write_bundle(bundle)
            manifest_path = bundle / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["starter_source"]["curation"]["criteria"]["minimum_plies"] = 1
            manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            database = AcsDatabase(root / "user-library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                with self.assertRaisesRegex(RuntimeError, "criteria authority"):
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

    def test_selected_record_digest_drift_fails_closed_before_application_start(self) -> None:
        with tempfile.TemporaryDirectory(prefix="accessible-chess-p0f-w2-record-drift-") as raw:
            root = Path(raw)
            bundle = root / "w2-starter"
            _write_bundle(bundle)
            manifest_path = bundle / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["starter_source"]["curation"]["selected_games"][0]["record_sha256"] = "0" * 64
            manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            database = AcsDatabase(root / "user-library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                with self.assertRaisesRegex(RuntimeError, "record_sha256 evidence does not match"):
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

    def test_packaged_sample_acsdb_import_is_explicit_readonly_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory(prefix="accessible-chess-p0f-w2-library-") as raw:
            root = Path(raw)
            bundle = root / "w2-starter"
            _write_bundle(bundle)
            packaged_database = bundle / "sample_library.acsdb"
            before_hash = _sha256(packaged_database)
            app, database, analysis = self._application(root, bundle)
            try:
                self.assertEqual(0, database.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0])
                first = app.browser_command("library", "library.import_packaged_sample_library", {})
                self.assertEqual("render", first["kind"])
                self.assertEqual("library", app.shell.current_route.route_id)
                self.assertEqual(_STARTER_COUNT, database.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0])
                self.assertEqual(1, database.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0])
                self.assertEqual(before_hash, _sha256(packaged_database))
                first_announcement = first["payload"]["announcement"]
                self.assertTrue(first_announcement)

                second = app.browser_command("library", "library.import_packaged_sample_library", {})
                self.assertEqual("render", second["kind"])
                self.assertEqual(_STARTER_COUNT, database.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0])
                self.assertEqual(1, database.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0])
                self.assertEqual(2, database.conn.execute("SELECT COUNT(*) FROM import_attempts").fetchone()[0])
                self.assertEqual(before_hash, _sha256(packaged_database))
                second_announcement = second["payload"]["announcement"]
                self.assertTrue(second_announcement)
                self.assertNotEqual(first_announcement, second_announcement)
            finally:
                app.shutdown()
                analysis.close()
                database.close()

    def test_post_start_packaged_pgn_tamper_fails_closed_before_open(self) -> None:
        with tempfile.TemporaryDirectory(prefix="accessible-chess-p0f-w2-late-pgn-") as raw:
            root = Path(raw)
            bundle = root / "w2-starter"
            _write_bundle(bundle)
            app, database, analysis = self._application(root, bundle)
            try:
                with (bundle / "starter_uk.pgn").open("a", encoding="utf-8") as handle:
                    handle.write("\n{post-start tamper}\n")
                result = app.browser_command("library", "library.open_packaged_starter_pgn", {})
                self.assertEqual("error", result["kind"])
                self.assertIsNone(app.session)
                self.assertEqual(0, database.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0])
            finally:
                app.shutdown()
                analysis.close()
                database.close()

    def test_post_start_packaged_acsdb_tamper_fails_closed_before_import(self) -> None:
        with tempfile.TemporaryDirectory(prefix="accessible-chess-p0f-w2-late-db-") as raw:
            root = Path(raw)
            bundle = root / "w2-starter"
            _write_bundle(bundle)
            packaged_database = bundle / "sample_library.acsdb"
            app, database, analysis = self._application(root, bundle)
            try:
                connection = sqlite3.connect(packaged_database)
                try:
                    connection.execute(
                        "UPDATE games SET pgn_text = pgn_text || ? WHERE id = (SELECT MIN(id) FROM games)",
                        ("\n{post-start tamper}",),
                    )
                    connection.commit()
                finally:
                    connection.close()
                quick = sqlite3.connect(packaged_database)
                try:
                    self.assertEqual("ok", quick.execute("PRAGMA quick_check").fetchone()[0])
                    self.assertEqual(_STARTER_COUNT, quick.execute("SELECT COUNT(*) FROM games").fetchone()[0])
                finally:
                    quick.close()

                result = app.browser_command("library", "library.import_packaged_sample_library", {})
                self.assertEqual("error", result["kind"])
                self.assertEqual(0, database.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0])
                self.assertEqual(0, database.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0])
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
                with self.assertRaisesRegex(RuntimeError, "byte length"):
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

    def test_extra_packaged_entry_fails_closed_before_application_start(self) -> None:
        with tempfile.TemporaryDirectory(prefix="accessible-chess-p0f-w2-extra-") as raw:
            root = Path(raw)
            bundle = root / "w2-starter"
            _write_bundle(bundle)
            (bundle / "unexpected").mkdir()
            database = AcsDatabase(root / "user-library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                with self.assertRaisesRegex(RuntimeError, "inventory is invalid"):
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

    def test_symlink_payload_fails_closed_even_when_target_bytes_match(self) -> None:
        with tempfile.TemporaryDirectory(prefix="accessible-chess-p0f-w2-symlink-") as raw:
            root = Path(raw)
            bundle = root / "w2-starter"
            _write_bundle(bundle)
            payload = bundle / "starter_uk.pgn"
            target = root / "same-starter.pgn"
            target.write_bytes(payload.read_bytes())
            payload.unlink()
            try:
                payload.symlink_to(target)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable on this host: {type(exc).__name__}")
            database = AcsDatabase(root / "user-library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                with self.assertRaisesRegex(RuntimeError, "regular non-reparse file"):
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

    def test_symlink_manifest_fails_closed_even_when_target_bytes_match(self) -> None:
        with tempfile.TemporaryDirectory(prefix="accessible-chess-p0f-w2-manifest-symlink-") as raw:
            root = Path(raw)
            bundle = root / "w2-starter"
            _write_bundle(bundle)
            manifest_path = bundle / "manifest.json"
            target = root / "same-manifest.json"
            target.write_bytes(manifest_path.read_bytes())
            manifest_path.unlink()
            try:
                manifest_path.symlink_to(target)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable on this host: {type(exc).__name__}")
            database = AcsDatabase(root / "user-library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                with self.assertRaisesRegex(RuntimeError, "regular non-reparse file"):
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