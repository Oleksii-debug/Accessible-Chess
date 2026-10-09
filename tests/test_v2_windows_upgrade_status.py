from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from acs.acsdb import ACSDB_SCHEMA_VERSION, AcsDatabase
from acs.version2_upgrade import (
    UserDataLayout,
    Version2UpgradeBusy,
    Version2UpgradeCoordinator,
    Version2UpgradeError,
    Version2UpgradeRecoveryError,
    Version2UpgradeReport,
)
from acs.version2_windows_upgrade_status import (
    UpgradeUiEventKind,
    UpgradeUiPhase,
    UpgradeUiStatus,
    Version2WindowsUpgradeStatusRunner,
)


class _ReportCoordinator(Version2UpgradeCoordinator):
    def __init__(self, phase_hook, report: Version2UpgradeReport) -> None:
        self._test_phase_hook = phase_hook
        self._test_report = report

    def run(self) -> Version2UpgradeReport:
        return self._test_report


class _FailureCoordinator(Version2UpgradeCoordinator):
    def __init__(self, phase_hook, error: Exception) -> None:
        self._test_phase_hook = phase_hook
        self._test_error = error

    def run(self) -> Version2UpgradeReport:
        raise self._test_error


class _CountingCoordinator(Version2UpgradeCoordinator):
    def __init__(self, phase_hook, counter: list[str], release: threading.Event) -> None:
        self._test_phase_hook = phase_hook
        self._test_counter = counter
        self._test_release = release

    def run(self) -> Version2UpgradeReport:
        self._test_counter.append(threading.current_thread().name)
        self._test_release.wait(5.0)
        return Version2UpgradeReport(
            "private-upgrade-id",
            "already_current",
            "private-backup-name",
            False,
            False,
            0,
            3,
            ACSDB_SCHEMA_VERSION,
            False,
        )


class Version2WindowsUpgradeStatusTests(unittest.TestCase):
    def _make_real_v1_library(self, path: Path) -> None:
        database = object.__new__(AcsDatabase)
        database.path = str(path)
        database.conn = sqlite3.connect(path)
        try:
            database.conn.row_factory = sqlite3.Row
            database.conn.execute("PRAGMA foreign_keys = ON")
            database._migrate_to_v1()
            self.assertTrue(database.conn.in_transaction)
            database.conn.execute("PRAGMA user_version = 1")
            database.conn.commit()
            database.conn.execute(
                "INSERT INTO sources(source_name,source_format,sha256,imported_at) "
                "VALUES(?,?,?,?)",
                (
                    "version1-library.pgn",
                    "pgn",
                    "1" * 64,
                    "2026-01-02T03:04:05+00:00",
                ),
            )
            database.conn.commit()
        finally:
            database.conn.close()

    @staticmethod
    def _flush(posted: list[callable]) -> None:
        while posted:
            posted.pop(0)()

    def test_real_v1_upgrade_runs_off_ui_thread_and_projects_bounded_semantic_phases(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            (root / "settings.json").write_text(
                json.dumps({"language": "en", "volume": 37}),
                encoding="utf-8",
            )
            (root / "books").mkdir()
            book = root / "books" / "course.bin"
            book.write_bytes(b"book\x00version-one\xff")
            library = root / "library.acsdb"
            self._make_real_v1_library(library)

            posted = []
            events = []
            sink_threads = []
            factory_threads = []

            def factory(phase_hook):
                factory_threads.append(threading.current_thread().name)
                return Version2UpgradeCoordinator(
                    UserDataLayout(root),
                    phase_hook=phase_hook,
                )

            def sink(event):
                sink_threads.append(threading.current_thread().name)
                events.append(event)

            runner = Version2WindowsUpgradeStatusRunner(
                factory,
                event_sink=sink,
                post_to_ui=posted.append,
            )
            self.assertTrue(runner.start())
            self.assertTrue(runner.wait(20.0))
            self.assertTrue(runner.join(1.0))
            self.assertEqual(events, [])
            self.assertTrue(posted)
            self._flush(posted)

            self.assertEqual(factory_threads, ["AccessibleChess-V2-Upgrade"])
            self.assertTrue(sink_threads)
            self.assertEqual(set(sink_threads), {threading.current_thread().name})
            self.assertEqual(events[0].kind, UpgradeUiEventKind.STARTED)
            self.assertEqual(events[0].status, UpgradeUiStatus.RUNNING)
            self.assertEqual(
                [event.phase for event in events if event.kind == UpgradeUiEventKind.PHASE],
                [
                    UpgradeUiPhase.BACKUP_READY,
                    UpgradeUiPhase.MIGRATING,
                    UpgradeUiPhase.SETTINGS_UPDATED,
                    UpgradeUiPhase.LIBRARY_UPDATED,
                    UpgradeUiPhase.VERIFYING,
                    UpgradeUiPhase.COMMITTED,
                ],
            )
            completed = events[-1]
            self.assertEqual(completed.kind, UpgradeUiEventKind.COMPLETED)
            self.assertEqual(completed.status, UpgradeUiStatus.UPGRADED)
            self.assertTrue(completed.settings_migrated)
            self.assertTrue(completed.library_migrated)
            self.assertEqual(completed.preserved_files, 1)
            self.assertEqual(completed.target_acsdb_schema, ACSDB_SCHEMA_VERSION)
            self.assertEqual(completed.focus_target, "app-root")

            report = runner.result
            self.assertIsNotNone(report)
            self.assertEqual(report.status, "upgraded")
            self.assertEqual(runner.error_code, None)
            self.assertEqual(book.read_bytes(), b"book\x00version-one\xff")
            with AcsDatabase(library) as reopened:
                self.assertEqual(reopened.verify_integrity(), ACSDB_SCHEMA_VERSION)
                self.assertEqual(
                    reopened.get_source(1)["source_name"],
                    "version1-library.pgn",
                )

            private_tokens = (
                str(root),
                report.upgrade_id,
                report.backup_name,
                ".v2-upgrade",
                "AccessibleChess.upgrade-backups",
            )
            rendered = "\n".join(repr(event) for event in events)
            for token in private_tokens:
                if token:
                    self.assertNotIn(token, rendered)

    def test_already_current_report_hides_upgrade_and_backup_identity(self) -> None:
        report = Version2UpgradeReport(
            "private-upgrade-id-123",
            "already_current",
            "private-backup-name-456",
            False,
            False,
            7,
            3,
            ACSDB_SCHEMA_VERSION,
            True,
        )
        posted = []
        events = []
        runner = Version2WindowsUpgradeStatusRunner(
            lambda hook: _ReportCoordinator(hook, report),
            event_sink=events.append,
            post_to_ui=posted.append,
        )
        self.assertTrue(runner.start())
        self.assertTrue(runner.wait(5.0))
        self._flush(posted)

        self.assertEqual(events[-1].kind, UpgradeUiEventKind.COMPLETED)
        self.assertEqual(events[-1].status, UpgradeUiStatus.CURRENT)
        self.assertEqual(events[-1].focus_target, "app-root")
        self.assertTrue(events[-1].recovered_interrupted_upgrade)
        rendered = repr(events[-1])
        self.assertNotIn(report.upgrade_id, rendered)
        self.assertNotIn(report.backup_name, rendered)
        self.assertIs(runner.result, report)

    def test_failure_classes_map_to_stable_path_free_codes(self) -> None:
        cases = (
            (Version2UpgradeBusy(r"C:\Users\Private\busy.lock"), "UPGRADE_BUSY"),
            (
                Version2UpgradeRecoveryError(r"D:\secret\backup\manifest.json"),
                "UPGRADE_RECOVERY_FAILED",
            ),
            (Version2UpgradeError(r"C:\private\library.acsdb"), "UPGRADE_FAILED"),
            (RuntimeError(r"C:\backend\traceback.txt"), "UPGRADE_UNAVAILABLE"),
        )
        for error, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                posted = []
                events = []
                runner = Version2WindowsUpgradeStatusRunner(
                    lambda hook, error=error: _FailureCoordinator(hook, error),
                    event_sink=events.append,
                    post_to_ui=posted.append,
                )
                self.assertTrue(runner.start())
                self.assertTrue(runner.wait(5.0))
                self._flush(posted)
                self.assertEqual(events[-1].kind, UpgradeUiEventKind.FAILED)
                self.assertEqual(events[-1].status, UpgradeUiStatus.FAILED)
                self.assertEqual(events[-1].error_code, expected_code)
                self.assertEqual(runner.error_code, expected_code)
                rendered = repr(events[-1])
                self.assertNotIn(str(error), rendered)
                self.assertNotIn("Users", rendered)
                self.assertNotIn("secret", rendered)
                self.assertNotIn("traceback", rendered.lower())
                self.assertIsNone(runner.result)

    def test_concurrent_start_is_one_shot_and_does_not_create_parallel_upgrade_workers(self) -> None:
        release = threading.Event()
        runs = []
        posted = []
        runner = Version2WindowsUpgradeStatusRunner(
            lambda hook: _CountingCoordinator(hook, runs, release),
            event_sink=lambda event: None,
            post_to_ui=posted.append,
        )
        callers = 16
        barrier = threading.Barrier(callers)
        answers = []
        answers_lock = threading.Lock()

        def call_start() -> None:
            barrier.wait()
            value = runner.start()
            with answers_lock:
                answers.append(value)

        threads = [threading.Thread(target=call_start) for _ in range(callers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(5.0)
        self.assertEqual(answers.count(True), 1)
        self.assertEqual(answers.count(False), callers - 1)
        self.assertEqual(runs, ["AccessibleChess-V2-Upgrade"])
        release.set()
        self.assertTrue(runner.wait(5.0))
        self.assertTrue(runner.join(1.0))
        self.assertFalse(runner.start())

    def test_poster_failure_never_falls_back_to_worker_thread_and_result_survives(self) -> None:
        report = Version2UpgradeReport(
            "private-id",
            "already_current",
            "private-backup",
            False,
            False,
            0,
            3,
            ACSDB_SCHEMA_VERSION,
            False,
        )
        sink_calls = []

        def failed_poster(callback):
            raise RuntimeError(r"C:\private\ui\post-failed")

        runner = Version2WindowsUpgradeStatusRunner(
            lambda hook: _ReportCoordinator(hook, report),
            event_sink=sink_calls.append,
            post_to_ui=failed_poster,
        )
        self.assertTrue(runner.start())
        self.assertTrue(runner.wait(5.0))
        self.assertEqual(sink_calls, [])
        self.assertIs(runner.result, report)
        self.assertIsNone(runner.error_code)

    def test_sink_failure_is_non_authoritative_and_no_cancel_contract_is_invented(self) -> None:
        report = Version2UpgradeReport(
            "private-id",
            "already_current",
            "private-backup",
            False,
            False,
            0,
            3,
            ACSDB_SCHEMA_VERSION,
            False,
        )
        posted = []

        def failed_sink(event):
            raise RuntimeError(r"C:\private\screenreader\sink.txt")

        runner = Version2WindowsUpgradeStatusRunner(
            lambda hook: _ReportCoordinator(hook, report),
            event_sink=failed_sink,
            post_to_ui=posted.append,
        )
        self.assertFalse(hasattr(runner, "cancel"))
        self.assertTrue(runner.start())
        self.assertTrue(runner.wait(5.0))
        self._flush(posted)
        self.assertIs(runner.result, report)
        self.assertIsNone(runner.error_code)


if __name__ == "__main__":
    unittest.main()
