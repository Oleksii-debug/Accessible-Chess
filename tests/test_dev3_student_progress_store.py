from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import acs.student_progress_store as student_progress_store_module

from acs.student_progress import (
    ReviewKind,
    STUDENT_PROGRESS_MAX_SNAPSHOT_RECORDS,
    STUDENT_PROGRESS_SNAPSHOT_SCHEMA_VERSION,
    StudentProgressLedger,
    StudentReviewRecord,
)
from acs.student_progress_store import (
    StudentProgressBusyError,
    StudentProgressConflictError,
    StudentProgressStore,
)


class StudentProgressStoreTests(unittest.TestCase):
    def _ledger(self, *, record_id: str = "r1", sequence: int = 1) -> StudentProgressLedger:
        ledger = StudentProgressLedger()
        ledger.append(
            StudentReviewRecord(
                record_id=record_id,
                student_id="student-1",
                session_id="session-1",
                kind=ReviewKind.GAME,
                source_id="game-1",
                source_revision="rev-1",
                sequence=sequence,
                attempts=0,
                mistakes=0,
                hints_used=0,
                completed=True,
            )
        )
        return ledger

    def test_create_load_and_update_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "student-progress.json"
            store = StudentProgressStore(path)
            ledger = self._ledger()

            revision1 = store.save(ledger, expected_revision=None)
            loaded1 = store.load()
            self.assertIsNotNone(loaded1)
            assert loaded1 is not None
            self.assertEqual(loaded1.revision, revision1)
            self.assertEqual(loaded1.ledger.snapshot(), ledger.snapshot())

            loaded1.ledger.append(
                StudentReviewRecord(
                    record_id="r2",
                    student_id="student-1",
                    session_id="session-1",
                    kind=ReviewKind.GAME,
                    source_id="game-2",
                    source_revision="rev-2",
                    sequence=2,
                    attempts=0,
                    mistakes=0,
                    hints_used=0,
                    completed=True,
                )
            )
            revision2 = store.save(
                loaded1.ledger,
                expected_revision=loaded1.revision,
            )
            self.assertNotEqual(revision2, revision1)
            loaded2 = store.load()
            self.assertIsNotNone(loaded2)
            assert loaded2 is not None
            self.assertEqual(loaded2.revision, revision2)
            self.assertEqual(
                [record.record_id for record in loaded2.ledger.records("student-1", "session-1")],
                ["r1", "r2"],
            )
            self.assertTrue(store._lock_path.is_file())

    def test_create_only_never_overwrites_existing_progress(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            store = StudentProgressStore(Path(raw_dir) / "student-progress.json")
            first = self._ledger()
            revision = store.save(first, expected_revision=None)
            original = store.path.read_bytes()

            with self.assertRaises(StudentProgressConflictError):
                store.save(self._ledger(record_id="other"), expected_revision=None)

            self.assertEqual(store.path.read_bytes(), original)
            self.assertEqual(store.load().revision, revision)  # type: ignore[union-attr]

    def test_stale_revision_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            store = StudentProgressStore(Path(raw_dir) / "student-progress.json")
            revision1 = store.save(self._ledger(), expected_revision=None)
            loaded = store.load()
            assert loaded is not None
            loaded.ledger.append(
                StudentReviewRecord(
                    record_id="r2",
                    student_id="student-1",
                    session_id="session-1",
                    kind=ReviewKind.GAME,
                    source_id="game-2",
                    source_revision="rev-2",
                    sequence=2,
                    attempts=0,
                    mistakes=0,
                    hints_used=0,
                    completed=True,
                )
            )
            revision2 = store.save(loaded.ledger, expected_revision=revision1)

            with self.assertRaises(StudentProgressConflictError):
                store.save(self._ledger(record_id="stale"), expected_revision=revision1)

            self.assertEqual(store.load().revision, revision2)  # type: ignore[union-attr]

    def test_legacy_directory_lock_reports_busy_without_touching_data(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            store = StudentProgressStore(Path(raw_dir) / "student-progress.json")
            revision = store.save(self._ledger(), expected_revision=None)
            original = store.path.read_bytes()
            store._lock_path.unlink()
            store._lock_path.mkdir()
            try:
                with self.assertRaises(StudentProgressBusyError):
                    store.save(self._ledger(record_id="r2"), expected_revision=revision)
            finally:
                store._lock_path.rmdir()
            self.assertEqual(store.path.read_bytes(), original)

    def test_peer_os_lock_reports_busy_then_abrupt_exit_releases_authority(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            store = StudentProgressStore(Path(raw_dir) / "student-progress.json")
            revision = store.save(self._ledger(), expected_revision=None)
            original = store.path.read_bytes()
            child_script = r'''
import os
from pathlib import Path
import sys
from acs.student_progress_store import _lock_writer_descriptor, _open_writer_lock
fd = _open_writer_lock(Path(sys.argv[1]))
_lock_writer_descriptor(fd)
print("LOCKED", flush=True)
sys.stdin.read(1)
os._exit(0)
'''
            child = subprocess.Popen(
                [sys.executable, "-c", child_script, os.fspath(store._lock_path)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                assert child.stdout is not None
                self.assertEqual(child.stdout.readline().strip(), "LOCKED")
                with self.assertRaises(StudentProgressBusyError):
                    store.save(self._ledger(record_id="blocked"), expected_revision=revision)
                self.assertEqual(store.path.read_bytes(), original)
                assert child.stdin is not None
                child.stdin.write("x")
                child.stdin.flush()
                self.assertEqual(child.wait(timeout=10), 0)
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=10)
                for stream in (child.stdin, child.stdout, child.stderr):
                    if stream is not None:
                        stream.close()

            replacement_revision = store.save(
                self._ledger(record_id="after-crash"),
                expected_revision=revision,
            )
            self.assertNotEqual(replacement_revision, revision)
            self.assertEqual(store.load().revision, replacement_revision)  # type: ignore[union-attr]


    @unittest.skipIf(
        os.name == "nt",
        "renaming an open storage directory is a POSIX adversarial injection",
    )
    def test_parent_directory_swap_after_kernel_acquire_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            storage = root / "profile"
            storage.mkdir()
            store = StudentProgressStore(storage / "student-progress.json")
            revision = store.save(self._ledger(), expected_revision=None)
            original = store.path.read_bytes()
            displaced = root / "displaced-profile"
            real_lock = student_progress_store_module._lock_writer_descriptor
            injected = False

            def swap_parent_after_lock(descriptor: int) -> None:
                nonlocal injected
                real_lock(descriptor)
                if not injected:
                    storage.rename(displaced)
                    storage.mkdir()
                    injected = True

            with patch.object(
                student_progress_store_module,
                "_lock_writer_descriptor",
                side_effect=swap_parent_after_lock,
            ):
                with self.assertRaisesRegex(
                    StudentProgressBusyError,
                    "directory changed during save",
                ):
                    store.save(
                        self._ledger(record_id="blocked-by-parent-swap"),
                        expected_revision=revision,
                    )

            self.assertTrue(injected)
            self.assertFalse(store.path.exists())
            self.assertEqual(
                original,
                (displaced / "student-progress.json").read_bytes(),
            )

            storage.rmdir()
            displaced.rename(storage)
            replacement_revision = store.save(
                self._ledger(record_id="after-parent-swap"),
                expected_revision=revision,
            )
            self.assertNotEqual(replacement_revision, revision)

    @unittest.skipIf(
        os.name == "nt",
        "replacing an open lock pathname is a POSIX adversarial injection",
    )
    def test_lock_path_swap_after_kernel_acquire_fails_closed_and_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            store = StudentProgressStore(root / "student-progress.json")
            revision = store.save(self._ledger(), expected_revision=None)
            original = store.path.read_bytes()
            replacement = root / "replacement.lock"
            replacement.write_bytes(b"\0")
            real_lock = student_progress_store_module._lock_writer_descriptor
            injected = False

            def swap_after_lock(descriptor: int) -> None:
                nonlocal injected
                real_lock(descriptor)
                if not injected:
                    os.replace(replacement, store._lock_path)
                    injected = True

            with patch.object(
                student_progress_store_module,
                "_lock_writer_descriptor",
                side_effect=swap_after_lock,
            ):
                with self.assertRaisesRegex(
                    StudentProgressBusyError,
                    "lock changed during save",
                ):
                    store.save(
                        self._ledger(record_id="blocked-by-lock-swap"),
                        expected_revision=revision,
                    )

            self.assertTrue(injected)
            self.assertEqual(original, store.path.read_bytes())
            self.assertTrue(store._lock_path.is_file())

            replacement_revision = store.save(
                self._ledger(record_id="after-lock-swap"),
                expected_revision=revision,
            )
            self.assertNotEqual(replacement_revision, revision)
            loaded = store.load()
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(replacement_revision, loaded.revision)

    def test_publication_failure_preserves_prior_file_and_retains_safe_temp(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            store = StudentProgressStore(Path(raw_dir) / "student-progress.json")
            revision = store.save(self._ledger(), expected_revision=None)
            original = store.path.read_bytes()
            loaded = store.load()
            assert loaded is not None
            loaded.ledger.append(
                StudentReviewRecord(
                    record_id="r2",
                    student_id="student-1",
                    session_id="session-1",
                    kind=ReviewKind.GAME,
                    source_id="game-2",
                    source_revision="rev-2",
                    sequence=2,
                    attempts=0,
                    mistakes=0,
                    hints_used=0,
                    completed=True,
                )
            )

            with patch(
                "acs.student_progress_store.os.rename"
            ) as forbidden_rename, patch(
                "acs.student_progress_store.os.replace",
                side_effect=OSError("publish failed"),
            ):
                with self.assertRaisesRegex(OSError, "publish failed"):
                    store.save(loaded.ledger, expected_revision=revision)

            self.assertEqual(store.path.read_bytes(), original)
            self.assertTrue(store._lock_path.is_file())
            forbidden_rename.assert_not_called()
            residues = list(store.path.parent.glob(f".{store.path.name}.*.tmp"))
            self.assertEqual(len(residues), 1)
            self.assertTrue(residues[0].is_file())

    def test_temp_preparation_failure_closes_descriptor_without_path_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            store = StudentProgressStore(Path(raw_dir) / "student-progress.json")
            real_require = student_progress_store_module._require_private_regular

            def reject_temp(metadata: os.stat_result, label: str) -> None:
                if label == "student progress temporary file":
                    raise ValueError("injected temporary validation failure")
                real_require(metadata, label)

            with patch.object(
                student_progress_store_module,
                "_require_private_regular",
                side_effect=reject_temp,
            ), patch("acs.student_progress_store.os.rename") as forbidden_rename:
                with self.assertRaisesRegex(
                    ValueError,
                    "injected temporary validation failure",
                ):
                    store.save(self._ledger(), expected_revision=None)

            forbidden_rename.assert_not_called()
            residues = list(store.path.parent.glob(f".{store.path.name}.*.tmp"))
            self.assertEqual(len(residues), 1)
            # On Windows this unlink fails if mkstemp's descriptor leaked; on
            # POSIX it still proves the retained residue is ordinary and owned.
            residues[0].unlink()
            self.assertFalse(residues[0].exists())

    def test_strict_envelope_and_snapshot_validation(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "student-progress.json"
            store = StudentProgressStore(path)

            for payload in (
                [],
                {"schema_version": 1},
                {"schema_version": 1, "snapshot": {}, "extra": True},
                {"schema_version": True, "snapshot": {}},
                {"schema_version": 99, "snapshot": {}},
                {"schema_version": 1, "snapshot": []},
            ):
                path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaises((TypeError, ValueError)):
                    store.load()

    def test_expected_revision_is_exact_lowercase_sha256(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            store = StudentProgressStore(Path(raw_dir) / "student-progress.json")
            ledger = self._ledger()
            for bad in (True, 1, "ABC", "a" * 63, "A" * 64, "g" * 64):
                with self.assertRaises((TypeError, ValueError)):
                    store.save(ledger, expected_revision=bad)  # type: ignore[arg-type]

    def test_serialized_store_contains_review_metadata_not_engine_answer_material(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            store = StudentProgressStore(Path(raw_dir) / "student-progress.json")
            store.save(self._ledger(), expected_revision=None)
            payload = store.path.read_text(encoding="utf-8")
            self.assertNotIn('"pv"', payload)
            self.assertNotIn('"score"', payload)
            self.assertIn('"record_id":"r1"', payload)

    def test_restore_rejects_oversized_record_list_before_record_validation(self) -> None:
        payload = {
            "schema_version": STUDENT_PROGRESS_SNAPSHOT_SCHEMA_VERSION,
            "records": [object()] * (STUDENT_PROGRESS_MAX_SNAPSHOT_RECORDS + 1),
        }
        with self.assertRaisesRegex(ValueError, "maximum record count"):
            StudentProgressLedger.restore(payload)

    def test_store_load_reads_only_bound_plus_one_before_rejecting(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "student-progress.json"
            path.write_bytes(b"x" * 129)
            store = StudentProgressStore(path)
            with patch(
                "acs.student_progress_store.STUDENT_PROGRESS_STORE_MAX_BYTES", 128
            ):
                with self.assertRaisesRegex(ValueError, "maximum size"):
                    store.load()

    def test_store_save_rejects_oversized_payload_before_publication(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            store = StudentProgressStore(Path(raw_dir) / "student-progress.json")
            with patch(
                "acs.student_progress_store.STUDENT_PROGRESS_STORE_MAX_BYTES", 64
            ):
                with self.assertRaisesRegex(ValueError, "payload exceeds maximum size"):
                    store.save(self._ledger(), expected_revision=None)
            self.assertFalse(store.path.exists())
            self.assertTrue(store._lock_path.is_file())
            self.assertEqual(
                list(store.path.parent.glob(f".{store.path.name}.*.tmp")),
                [],
            )

    def test_store_round_trip_remains_supported_under_default_bound(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            store = StudentProgressStore(Path(raw_dir) / "student-progress.json")
            ledger = self._ledger()
            revision = store.save(ledger, expected_revision=None)
            loaded = store.load()
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.revision, revision)
            self.assertEqual(loaded.ledger.snapshot(), ledger.snapshot())


if __name__ == "__main__":
    unittest.main()
