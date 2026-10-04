from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

import acs.training_progress_store as progress_store_module
from acs.chesscore import Board
from acs.training import ExerciseDefinition, ExerciseSession, ExerciseStep
from acs.training_progress_store import (
    MAX_TRAINING_PROGRESS_BYTES,
    TrainingProgressBusyError,
    TrainingProgressConflictError,
    TrainingProgressResourceError,
    TrainingProgressStore,
)


def _hold_training_progress_lock(path: str, ready) -> None:
    """Spawn-target: own the real OS lock until the process is terminated."""
    store = TrainingProgressStore(path)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    descriptor = store._open_lock_descriptor()
    store._lock_descriptor(descriptor)
    ready.set()
    time.sleep(60)


class TrainingProgressCrashRecoveryTests(unittest.TestCase):
    @staticmethod
    def _definition() -> ExerciseDefinition:
        return ExerciseDefinition(
            "w2-training-progress-recovery",
            Board.START,
            (ExerciseStep(frozenset({"e4"})),),
        )

    def test_load_missing_nested_progress_path_is_empty_and_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "never-created" / "nested" / "training-progress.json"
            self.assertFalse(path.parent.exists())

            loaded = TrainingProgressStore(path).load(self._definition())

            self.assertIsNone(loaded)
            self.assertFalse(path.parent.exists())

    def test_persistent_lock_file_residue_does_not_block_save(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "training-progress.json"
            store = TrainingProgressStore(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            store._lock_path.write_bytes(b"\0")

            session = ExerciseSession(self._definition())
            revision = store.save(session, expected_revision=None)

            self.assertEqual(64, len(revision))
            loaded = store.load(self._definition())
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(revision, loaded.revision)
            self.assertTrue(store._lock_path.is_file())

    def test_live_writer_is_busy_but_process_death_releases_lock(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "training-progress.json"
            context = multiprocessing.get_context("spawn")
            ready = context.Event()
            process = context.Process(
                target=_hold_training_progress_lock,
                args=(str(path), ready),
            )
            process.start()
            self.addCleanup(
                lambda: process.is_alive() and (process.terminate(), process.join(10))
            )
            self.assertTrue(ready.wait(15), "child did not acquire training progress lock")

            store = TrainingProgressStore(path)
            session = ExerciseSession(self._definition())
            with self.assertRaises(TrainingProgressBusyError):
                store.save(session, expected_revision=None)

            process.terminate()
            process.join(15)
            self.assertFalse(process.is_alive(), "terminated writer did not exit")

            revision = store.save(session, expected_revision=None)
            loaded = store.load(self._definition())
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(revision, loaded.revision)

    def test_legacy_lock_directory_is_not_unsafely_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "training-progress.json"
            store = TrainingProgressStore(path)
            store._lock_path.mkdir(parents=True)
            session = ExerciseSession(self._definition())

            with self.assertRaises(TrainingProgressBusyError):
                store.save(session, expected_revision=None)
            self.assertTrue(store._lock_path.is_dir())

            store._lock_path.rmdir()
            revision = store.save(session, expected_revision=None)
            self.assertEqual(64, len(revision))

    def test_lock_path_swap_after_precheck_never_writes_target(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "training-progress.json"
            store = TrainingProgressStore(path)
            store._lock_path.write_bytes(b"\0")
            target = root / "outside-user-data.bin"
            target.write_bytes(b"")

            real_lstat = os.lstat
            swapped = False

            def racing_lstat(candidate):
                nonlocal swapped
                metadata = real_lstat(candidate)
                if Path(candidate) == store._lock_path and not swapped:
                    swapped = True
                    store._lock_path.unlink()
                    try:
                        store._lock_path.symlink_to(target)
                    except (OSError, NotImplementedError):
                        self.skipTest("symlink creation is unavailable on this platform")
                return metadata

            with mock.patch("acs.training_progress_store.os.lstat", side_effect=racing_lstat):
                with self.assertRaises(TrainingProgressBusyError):
                    store.save(
                        ExerciseSession(self._definition()),
                        expected_revision=None,
                    )

            self.assertTrue(swapped)
            self.assertEqual(b"", target.read_bytes())
            self.assertTrue(store._lock_path.is_symlink())
            self.assertFalse(path.exists())


    def test_regular_lock_replacement_between_precheck_and_open_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "training-progress.json"
            store = TrainingProgressStore(path)
            store._lock_path.write_bytes(b"\0")
            replacement = root / "replacement-lock.bin"
            replacement.write_bytes(b"replacement")

            real_open = progress_store_module._open_no_reparse
            swapped = False

            def racing_open(candidate: Path, *, create: bool, writable: bool = False) -> int:
                nonlocal swapped
                if Path(candidate) == store._lock_path and create and not swapped:
                    swapped = True
                    os.replace(replacement, store._lock_path)
                return real_open(Path(candidate), create=create, writable=writable)

            with mock.patch(
                "acs.training_progress_store._open_no_reparse",
                side_effect=racing_open,
            ):
                with self.assertRaises(TrainingProgressBusyError):
                    store.save(
                        ExerciseSession(self._definition()),
                        expected_revision=None,
                    )

            self.assertTrue(swapped)
            self.assertEqual(b"replacement", store._lock_path.read_bytes())
            self.assertFalse(path.exists())

    def test_regular_lock_replacement_after_os_lock_fails_before_progress_write(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "training-progress.json"
            store = TrainingProgressStore(path)
            replacement = root / "replacement-lock.bin"
            replacement.write_bytes(b"replacement")

            real_lock = store._lock_descriptor
            swapped = False

            def racing_lock(descriptor: int) -> None:
                nonlocal swapped
                real_lock(descriptor)
                os.replace(replacement, store._lock_path)
                swapped = True

            with mock.patch.object(store, "_lock_descriptor", side_effect=racing_lock):
                with self.assertRaisesRegex(
                    TrainingProgressBusyError,
                    "lock changed while held",
                ):
                    store.save(
                        ExerciseSession(self._definition()),
                        expected_revision=None,
                    )

            self.assertTrue(swapped)
            self.assertEqual(b"replacement", store._lock_path.read_bytes())
            self.assertFalse(path.exists())

    def test_lock_replacement_during_transaction_aborts_before_temp_publication(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "training-progress.json"
            store = TrainingProgressStore(path)
            replacement = root / "replacement-lock.bin"
            replacement.write_bytes(b"replacement")
            real_read = store._read_progress_bytes
            swapped = False

            def racing_read(*, missing_ok: bool):
                nonlocal swapped
                result = real_read(missing_ok=missing_ok)
                if not swapped:
                    os.replace(replacement, store._lock_path)
                    swapped = True
                return result

            with mock.patch.object(
                store,
                "_read_progress_bytes",
                side_effect=racing_read,
            ):
                with self.assertRaisesRegex(
                    TrainingProgressBusyError,
                    "lock changed while held",
                ):
                    store.save(
                        ExerciseSession(self._definition()),
                        expected_revision=None,
                    )

            self.assertTrue(swapped)
            self.assertEqual(b"replacement", store._lock_path.read_bytes())
            self.assertFalse(path.exists())
            self.assertEqual([], list(root.glob(f".{path.name}.*.tmp")))

    def test_lock_replacement_prevents_noop_save_from_acknowledging_success(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "training-progress.json"
            definition = self._definition()
            initial_store = TrainingProgressStore(path)
            session = ExerciseSession(definition)
            revision = initial_store.save(session, expected_revision=None)

            store = TrainingProgressStore(path)
            replacement = root / "replacement-lock.bin"
            replacement.write_bytes(b"replacement")
            real_read = store._read_progress_bytes
            swapped = False

            def racing_read(*, missing_ok: bool):
                nonlocal swapped
                result = real_read(missing_ok=missing_ok)
                if not swapped:
                    os.replace(replacement, store._lock_path)
                    swapped = True
                return result

            with mock.patch.object(
                store,
                "_read_progress_bytes",
                side_effect=racing_read,
            ):
                with self.assertRaisesRegex(
                    TrainingProgressBusyError,
                    "lock changed while held",
                ):
                    store.save(session, expected_revision=revision)

            self.assertTrue(swapped)
            loaded = TrainingProgressStore(path).load(definition)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(revision, loaded.revision)
            self.assertEqual(0, loaded.session.step_index)

    def test_lock_replacement_after_publication_withholds_success_acknowledgement(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "training-progress.json"
            definition = self._definition()
            store = TrainingProgressStore(path)
            initial = ExerciseSession(definition)
            revision = store.save(initial, expected_revision=None)

            advanced = ExerciseSession(definition)
            advanced.submit("e4")
            replacement = root / "replacement-lock.bin"
            replacement.write_bytes(b"replacement")
            real_sync = progress_store_module._sync_published_path
            swapped = False

            def racing_sync(candidate: Path) -> None:
                nonlocal swapped
                os.replace(replacement, store._lock_path)
                swapped = True
                real_sync(candidate)

            with mock.patch(
                "acs.training_progress_store._sync_published_path",
                side_effect=racing_sync,
            ):
                with self.assertRaisesRegex(
                    TrainingProgressBusyError,
                    "lock changed while held",
                ):
                    store.save(advanced, expected_revision=revision)

            self.assertTrue(swapped)
            loaded = TrainingProgressStore(path).load(definition)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(1, loaded.session.step_index)
            self.assertEqual(("e4",), loaded.session.accepted_path)

    def test_progress_path_swap_before_open_never_reads_redirected_target(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            definition = self._definition()
            path = root / "training-progress.json"
            target = root / "outside-progress.json"
            valid_target = json.dumps(
                {
                    "schema_version": 1,
                    "snapshot": ExerciseSession(definition).snapshot(),
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
            target.write_bytes(valid_target)
            path.write_bytes(b"original-placeholder")
            store = TrainingProgressStore(path)

            real_open = progress_store_module._open_no_reparse
            swapped = False

            def racing_open(candidate: Path, *, create: bool) -> int:
                nonlocal swapped
                if Path(candidate) == path and not create and not swapped:
                    swapped = True
                    path.unlink()
                    try:
                        path.symlink_to(target)
                    except (OSError, NotImplementedError):
                        self.skipTest("symlink creation is unavailable on this platform")
                return real_open(Path(candidate), create=create)

            with mock.patch(
                "acs.training_progress_store._open_no_reparse",
                side_effect=racing_open,
            ):
                with self.assertRaisesRegex(ValueError, "could not be inspected"):
                    store.load(definition)

            self.assertTrue(swapped)
            self.assertEqual(valid_target, target.read_bytes())
            self.assertTrue(path.is_symlink())

    def test_oversized_existing_progress_fails_before_parse_or_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "training-progress.json"
            oversized = b"{" + (b" " * MAX_TRAINING_PROGRESS_BYTES) + b"}"
            path.write_bytes(oversized)
            store = TrainingProgressStore(path)

            with self.assertRaises(TrainingProgressResourceError):
                store.load(self._definition())

            expected = hashlib.sha256(oversized).hexdigest()
            with self.assertRaises(TrainingProgressResourceError):
                store.save(
                    ExerciseSession(self._definition()),
                    expected_revision=expected,
                )
            self.assertEqual(oversized, path.read_bytes())

    def test_generated_snapshot_cannot_publish_beyond_store_bound(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "training-progress.json"
            session = ExerciseSession(self._definition())
            oversized_snapshot = session.snapshot()
            oversized_snapshot["exercise_id"] = "x" * (MAX_TRAINING_PROGRESS_BYTES + 1)
            store = TrainingProgressStore(path)

            with mock.patch.object(session, "snapshot", return_value=oversized_snapshot):
                with self.assertRaises(TrainingProgressResourceError):
                    store.save(session, expected_revision=None)
            self.assertFalse(path.exists())

    def test_duplicate_json_object_keys_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "training-progress.json"
            session = ExerciseSession(self._definition())
            snapshot_text = json.dumps(
                session.snapshot(), ensure_ascii=False, separators=(",", ":")
            )
            path.write_text(
                '{"schema_version":1,"schema_version":1,"snapshot":'
                + snapshot_text
                + "}",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "duplicate JSON object keys"):
                TrainingProgressStore(path).load(self._definition())

    def test_progress_symlink_is_not_followed_or_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "outside.json"
            path = root / "training-progress.json"
            target.write_text("outside-user-data", encoding="utf-8")
            try:
                path.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation is unavailable on this platform")

            store = TrainingProgressStore(path)
            with self.assertRaisesRegex(ValueError, "could not be inspected"):
                store.load(self._definition())
            with self.assertRaisesRegex(ValueError, "could not be inspected"):
                store.save(
                    ExerciseSession(self._definition()),
                    expected_revision=None,
                )
            self.assertEqual("outside-user-data", target.read_text(encoding="utf-8"))
            self.assertTrue(path.is_symlink())

    def test_storage_parent_symlink_is_rejected_without_touching_target(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target_dir = root / "outside"
            target_dir.mkdir()
            linked_dir = root / "progress-link"
            try:
                linked_dir.symlink_to(target_dir, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("directory symlink creation is unavailable on this platform")
            path = linked_dir / "training-progress.json"
            store = TrainingProgressStore(path)

            with self.assertRaisesRegex(ValueError, "storage directory"):
                store.load(self._definition())
            with self.assertRaisesRegex(ValueError, "storage directory"):
                store.save(
                    ExerciseSession(self._definition()),
                    expected_revision=None,
                )

            self.assertEqual([], list(target_dir.iterdir()))

    def test_storage_parent_identity_change_during_save_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            parent = root / "progress"
            replacement_parent = root / "replacement"
            parent.mkdir()
            replacement_parent.mkdir()
            path = parent / "training-progress.json"
            store = TrainingProgressStore(path)
            session = ExerciseSession(self._definition())

            real_lstat = os.lstat
            replacement_metadata = real_lstat(replacement_parent)
            parent_checks = 0

            def racing_lstat(candidate):
                nonlocal parent_checks
                if Path(candidate) == parent:
                    parent_checks += 1
                    if parent_checks >= 3:
                        return replacement_metadata
                return real_lstat(candidate)

            with mock.patch(
                "acs.training_progress_store.os.lstat",
                side_effect=racing_lstat,
            ):
                with self.assertRaisesRegex(ValueError, "changed during the transaction"):
                    store.save(session, expected_revision=None)

            self.assertGreaterEqual(parent_checks, 3)
            self.assertFalse(path.exists())

    def test_save_runs_durability_barrier_before_acknowledging_revision(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "training-progress.json"
            store = TrainingProgressStore(path)
            session = ExerciseSession(self._definition())

            with mock.patch(
                "acs.training_progress_store._sync_published_path",
                wraps=progress_store_module._sync_published_path,
            ) as sync_published:
                revision = store.save(session, expected_revision=None)

            sync_published.assert_called_once_with(path)
            loaded = TrainingProgressStore(path).load(self._definition())
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(revision, loaded.revision)

    def test_windows_durability_barrier_uses_bound_nonreparse_descriptor(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "training-progress.json"
            path.write_bytes(b"durable")
            descriptor = os.open(path, os.O_RDWR)

            with (
                mock.patch.object(progress_store_module.os, "name", "nt"),
                mock.patch(
                    "acs.training_progress_store._open_no_reparse",
                    return_value=descriptor,
                ) as open_bound,
                mock.patch("acs.training_progress_store.os.fsync") as fsync,
            ):
                progress_store_module._sync_published_path(path)

            open_bound.assert_called_once_with(path, create=False, writable=True)
            fsync.assert_called_once_with(descriptor)
            with self.assertRaises(OSError):
                os.fstat(descriptor)

    def test_durability_barrier_failure_withholds_success_after_visible_replace(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "training-progress.json"
            definition = self._definition()
            store = TrainingProgressStore(path)
            initial = ExerciseSession(definition)
            initial_revision = store.save(initial, expected_revision=None)

            advanced = ExerciseSession(definition)
            advanced.submit("e4")
            with mock.patch(
                "acs.training_progress_store._sync_published_path",
                side_effect=OSError("injected durability failure"),
            ):
                with self.assertRaisesRegex(OSError, "injected durability failure"):
                    store.save(advanced, expected_revision=initial_revision)

            # Atomic replace may already be visible. The important contract is
            # that save did not falsely acknowledge durability.
            loaded = TrainingProgressStore(path).load(definition)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(1, loaded.session.step_index)
            self.assertEqual(("e4",), loaded.session.accepted_path)

    def test_external_change_during_save_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "training-progress.json"
            store = TrainingProgressStore(path)
            definition = self._definition()
            first_session = ExerciseSession(definition)
            revision = store.save(first_session, expected_revision=None)
            original = path.read_bytes()

            next_session = ExerciseSession(definition)
            next_session.submit("e4")
            external = b'{"external":"writer"}'
            real_read = store._read_progress_bytes
            calls = 0

            def racing_read(*, missing_ok: bool):
                nonlocal calls
                calls += 1
                if calls == 2:
                    path.write_bytes(external)
                return real_read(missing_ok=missing_ok)

            with mock.patch.object(store, "_read_progress_bytes", side_effect=racing_read):
                with self.assertRaises(TrainingProgressConflictError):
                    store.save(next_session, expected_revision=revision)

            self.assertGreaterEqual(calls, 2)
            self.assertEqual(external, path.read_bytes())
            self.assertNotEqual(original, path.read_bytes())

    def test_atomic_replace_failure_preserves_progress_and_restart_retry_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "training-progress.json"
            definition = self._definition()
            store = TrainingProgressStore(path)
            initial_session = ExerciseSession(definition)
            initial_revision = store.save(initial_session, expected_revision=None)
            original = path.read_bytes()

            advanced = ExerciseSession(definition)
            advanced.submit("e4")
            with mock.patch(
                "acs.training_progress_store._replace_published_path",
                side_effect=OSError("injected replace failure"),
            ):
                with self.assertRaises(OSError):
                    store.save(advanced, expected_revision=initial_revision)

            self.assertEqual(original, path.read_bytes())
            self.assertEqual([], list(path.parent.glob(f".{path.name}.*.tmp")))

            restarted = TrainingProgressStore(path)
            loaded = restarted.load(definition)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(initial_revision, loaded.revision)
            self.assertEqual(0, loaded.session.step_index)

            retry_revision = restarted.save(
                advanced,
                expected_revision=initial_revision,
            )
            reloaded = TrainingProgressStore(path).load(definition)
            self.assertIsNotNone(reloaded)
            assert reloaded is not None
            self.assertEqual(retry_revision, reloaded.revision)
            self.assertNotEqual(initial_revision, retry_revision)
            self.assertEqual(1, reloaded.session.step_index)
            self.assertEqual(("e4",), reloaded.session.accepted_path)


if __name__ == "__main__":
    unittest.main()
