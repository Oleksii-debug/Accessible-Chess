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
    TrainingProgressDurabilityUnknownError,
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
            replacement.write_bytes(b"\0")

            real_open = progress_store_module._open_no_reparse
            swapped = False

            def racing_open(
                candidate: Path,
                *,
                create: bool,
                writable: bool = False,
                exclusive: bool = False,
            ) -> int:
                nonlocal swapped
                if (
                    Path(candidate) == store._lock_path
                    and writable
                    and not create
                    and not exclusive
                    and not swapped
                ):
                    swapped = True
                    os.replace(replacement, store._lock_path)
                return real_open(
                    Path(candidate),
                    create=create,
                    writable=writable,
                    exclusive=exclusive,
                )

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
            self.assertEqual(b"\0", store._lock_path.read_bytes())
            self.assertFalse(path.exists())

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
            with self.assertRaisesRegex(
                ValueError,
                "could not be inspected|not a regular file",
            ):
                store.load(self._definition())
            with self.assertRaisesRegex(
                ValueError,
                "could not be inspected|not a regular file",
            ):
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
                with self.assertRaises(TrainingProgressDurabilityUnknownError) as raised:
                    store.save(advanced, expected_revision=initial_revision)

            # Atomic replace may already be visible. The important contract is
            # that save did not falsely acknowledge durability.
            loaded = TrainingProgressStore(path).load(definition)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(1, loaded.session.step_index)
            self.assertEqual(("e4",), loaded.session.accepted_path)
            self.assertEqual(loaded.revision, raised.exception.published_revision)
            self.assertIsInstance(raised.exception.__cause__, OSError)

    def test_missing_target_appearance_after_publication_read_is_a_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "training-progress.json"
            definition = self._definition()
            store = TrainingProgressStore(path)
            session = ExerciseSession(definition)
            external_payload = json.dumps(
                {
                    "schema_version": 1,
                    "snapshot": session.snapshot(),
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
            real_read = store._read_progress_bytes
            calls = 0
            injected = False

            def appear_after_publication_read(*, missing_ok: bool):
                nonlocal calls, injected
                calls += 1
                raw = real_read(missing_ok=missing_ok)
                if calls == 2 and raw is None:
                    path.write_bytes(external_payload)
                    injected = True
                return raw

            with mock.patch.object(
                store,
                "_read_progress_bytes",
                side_effect=appear_after_publication_read,
            ):
                with self.assertRaises(TrainingProgressConflictError):
                    store.save(session, expected_revision=None)

            self.assertTrue(injected)
            self.assertEqual(external_payload, path.read_bytes())
            loaded = TrainingProgressStore(path).load(definition)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(0, loaded.session.step_index)

    def test_same_byte_target_swap_during_noop_snapshot_is_a_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "training-progress.json"
            definition = self._definition()
            store = TrainingProgressStore(path)
            session = ExerciseSession(definition)
            revision = store.save(session, expected_revision=None)
            original = path.read_bytes()
            original_identity = os.lstat(path)
            real_snapshot = session.snapshot
            injected = False

            def snapshot_after_same_byte_swap():
                nonlocal injected
                snapshot = real_snapshot()
                replacement = root / "same-byte-during-noop-snapshot.json"
                replacement.write_bytes(original)
                os.replace(replacement, path)
                injected = True
                return snapshot

            with mock.patch.object(
                session,
                "snapshot",
                side_effect=snapshot_after_same_byte_swap,
            ):
                with self.assertRaises(TrainingProgressConflictError):
                    store.save(session, expected_revision=revision)

            self.assertTrue(injected)
            self.assertEqual(original, path.read_bytes())
            self.assertFalse(os.path.samestat(original_identity, os.lstat(path)))
            loaded = TrainingProgressStore(path).load(definition)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(0, loaded.session.step_index)
            self.assertEqual(revision, loaded.revision)

    def test_same_byte_target_swap_before_initial_read_is_a_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "training-progress.json"
            definition = self._definition()
            store = TrainingProgressStore(path)
            initial = ExerciseSession(definition)
            revision = store.save(initial, expected_revision=None)
            original = path.read_bytes()
            original_identity = os.lstat(path)

            advanced = ExerciseSession(definition)
            advanced.submit("e4")
            real_read = store._read_progress_bytes
            calls = 0
            injected = False

            def swap_before_initial_read(*, missing_ok: bool):
                nonlocal calls, injected
                calls += 1
                if calls == 1:
                    replacement = root / "same-byte-before-initial-read.json"
                    replacement.write_bytes(original)
                    os.replace(replacement, path)
                    injected = True
                return real_read(missing_ok=missing_ok)

            with mock.patch.object(
                store,
                "_read_progress_bytes",
                side_effect=swap_before_initial_read,
            ):
                with self.assertRaises(TrainingProgressConflictError):
                    store.save(advanced, expected_revision=revision)

            self.assertTrue(injected)
            self.assertEqual(original, path.read_bytes())
            self.assertFalse(os.path.samestat(original_identity, os.lstat(path)))
            loaded = TrainingProgressStore(path).load(definition)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(0, loaded.session.step_index)
            self.assertEqual(revision, loaded.revision)

    def test_same_byte_target_swap_after_publication_read_is_a_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "training-progress.json"
            definition = self._definition()
            store = TrainingProgressStore(path)
            initial = ExerciseSession(definition)
            revision = store.save(initial, expected_revision=None)
            original = path.read_bytes()
            original_identity = os.lstat(path)

            advanced = ExerciseSession(definition)
            advanced.submit("e4")
            real_read = store._read_progress_bytes
            calls = 0
            injected = False

            def swap_after_publication_read(*, missing_ok: bool):
                nonlocal calls, injected
                calls += 1
                raw = real_read(missing_ok=missing_ok)
                if calls == 2 and raw is not None:
                    replacement = root / "same-byte-after-publication-read.json"
                    replacement.write_bytes(raw)
                    os.replace(replacement, path)
                    injected = True
                return raw

            with mock.patch.object(
                store,
                "_read_progress_bytes",
                side_effect=swap_after_publication_read,
            ):
                with self.assertRaises(TrainingProgressConflictError):
                    store.save(advanced, expected_revision=revision)

            self.assertTrue(injected)
            self.assertEqual(original, path.read_bytes())
            self.assertFalse(os.path.samestat(original_identity, os.lstat(path)))
            loaded = TrainingProgressStore(path).load(definition)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(0, loaded.session.step_index)
            self.assertEqual(revision, loaded.revision)

    def test_same_byte_target_swap_after_publication_identity_is_a_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "training-progress.json"
            definition = self._definition()
            store = TrainingProgressStore(path)
            initial = ExerciseSession(definition)
            revision = store.save(initial, expected_revision=None)
            original = path.read_bytes()

            advanced = ExerciseSession(definition)
            advanced.submit("e4")
            real_identity = store._progress_path_identity
            identity_checks = 0
            injected = False

            def swap_after_publication_identity(*, missing_ok: bool):
                nonlocal identity_checks, injected
                identity_checks += 1
                identity = real_identity(missing_ok=missing_ok)
                if identity_checks == 3 and identity is not None:
                    replacement = root / "same-byte-after-publication-identity.json"
                    replacement.write_bytes(original)
                    os.replace(replacement, path)
                    injected = True
                return identity

            with mock.patch.object(
                store,
                "_progress_path_identity",
                side_effect=swap_after_publication_identity,
            ):
                with self.assertRaises(TrainingProgressConflictError):
                    store.save(advanced, expected_revision=revision)

            self.assertTrue(injected)
            self.assertGreaterEqual(identity_checks, 4)
            self.assertEqual(original, path.read_bytes())
            loaded = TrainingProgressStore(path).load(definition)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(0, loaded.session.step_index)
            self.assertEqual(revision, loaded.revision)

    def test_missing_target_appearance_after_publication_identity_is_a_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "training-progress.json"
            definition = self._definition()
            store = TrainingProgressStore(path)
            session = ExerciseSession(definition)
            external_payload = json.dumps(
                {
                    "schema_version": 1,
                    "snapshot": session.snapshot(),
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
            real_identity = store._progress_path_identity
            identity_checks = 0
            injected = False

            def appear_after_publication_identity(*, missing_ok: bool):
                nonlocal identity_checks, injected
                identity_checks += 1
                identity = real_identity(missing_ok=missing_ok)
                if identity_checks == 3 and identity is None:
                    path.write_bytes(external_payload)
                    injected = True
                return identity

            with mock.patch.object(
                store,
                "_progress_path_identity",
                side_effect=appear_after_publication_identity,
            ):
                with self.assertRaises(TrainingProgressConflictError):
                    store.save(session, expected_revision=None)

            self.assertTrue(injected)
            self.assertGreaterEqual(identity_checks, 4)
            self.assertEqual(external_payload, path.read_bytes())
            loaded = TrainingProgressStore(path).load(definition)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(0, loaded.session.step_index)

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

    def test_preexisting_empty_lock_is_never_initialized_in_place(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "training-progress.json"
            store = TrainingProgressStore(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            store._lock_path.write_bytes(b"")

            with mock.patch(
                "acs.training_progress_store.time.sleep",
                return_value=None,
            ):
                with self.assertRaises(TrainingProgressBusyError):
                    store.save(
                        ExerciseSession(self._definition()),
                        expected_revision=None,
                    )

            self.assertEqual(b"", store._lock_path.read_bytes())
            self.assertFalse(path.exists())

    def test_preexisting_noncanonical_lock_marker_is_rejected_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "training-progress.json"
            store = TrainingProgressStore(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            store._lock_path.write_bytes(b"x")

            with self.assertRaises(TrainingProgressBusyError):
                store.save(
                    ExerciseSession(self._definition()),
                    expected_revision=None,
                )

            self.assertEqual(b"x", store._lock_path.read_bytes())
            self.assertFalse(path.exists())

    def test_hardlinked_lock_is_rejected_without_touching_peer(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "training-progress.json"
            peer = root / "peer-lock.bin"
            peer.write_bytes(b"\0")
            store = TrainingProgressStore(path)
            try:
                os.link(peer, store._lock_path)
            except (OSError, NotImplementedError):
                self.skipTest("hard links are unavailable on this platform")

            with self.assertRaises(TrainingProgressBusyError):
                store.save(
                    ExerciseSession(self._definition()),
                    expected_revision=None,
                )

            self.assertEqual(b"\0", peer.read_bytes())
            self.assertTrue(store._lock_path.exists())
            self.assertFalse(path.exists())

    def test_hardlinked_progress_file_is_not_accepted_as_private_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            definition = self._definition()
            path = root / "training-progress.json"
            peer = root / "peer-progress.json"
            peer.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "snapshot": ExerciseSession(definition).snapshot(),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ),
                encoding="utf-8",
            )
            try:
                os.link(peer, path)
            except (OSError, NotImplementedError):
                self.skipTest("hard links are unavailable on this platform")

            with self.assertRaisesRegex(ValueError, "not private"):
                TrainingProgressStore(path).load(definition)

            self.assertTrue(path.exists())
            self.assertEqual(peer.read_bytes(), path.read_bytes())

    def test_existing_progress_disappearance_between_lstat_and_open_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "training-progress.json"
            definition = self._definition()
            store = TrainingProgressStore(path)
            store.save(ExerciseSession(definition), expected_revision=None)

            real_open = progress_store_module._open_no_reparse
            removed = False

            def disappearing_open(
                candidate: Path,
                *,
                create: bool,
                writable: bool = False,
                exclusive: bool = False,
            ) -> int:
                nonlocal removed
                candidate = Path(candidate)
                if candidate == path and not create and not removed:
                    removed = True
                    path.unlink()
                return real_open(
                    candidate,
                    create=create,
                    writable=writable,
                    exclusive=exclusive,
                )

            with mock.patch(
                "acs.training_progress_store._open_no_reparse",
                side_effect=disappearing_open,
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "changed while being opened",
                ):
                    TrainingProgressStore(path).load(definition)

            self.assertTrue(removed)
            self.assertFalse(path.exists())

    @unittest.skipIf(
        os.name == "nt",
        "replacing an open progress pathname is a POSIX-specific race probe",
    )

    def test_missing_progress_appearance_between_lstat_and_open_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "training-progress.json"
            definition = self._definition()
            seed_store = TrainingProgressStore(path)
            seed_store.save(ExerciseSession(definition), expected_revision=None)
            valid_payload = path.read_bytes()
            path.unlink()
            self.assertFalse(path.exists())

            real_open = progress_store_module._open_no_reparse
            inserted = False

            def appearing_open(
                candidate: Path,
                *,
                create: bool,
                writable: bool = False,
                exclusive: bool = False,
            ) -> int:
                nonlocal inserted
                candidate = Path(candidate)
                if candidate == path and not create and not inserted:
                    inserted = True
                    path.write_bytes(valid_payload)
                return real_open(
                    candidate,
                    create=create,
                    writable=writable,
                    exclusive=exclusive,
                )

            with mock.patch(
                "acs.training_progress_store._open_no_reparse",
                side_effect=appearing_open,
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "changed while being opened",
                ):
                    TrainingProgressStore(path).load(definition)

            self.assertTrue(inserted)
            self.assertTrue(path.is_file())
            self.assertEqual(path.read_bytes(), valid_payload)

    @unittest.skipIf(
        os.name == "nt",
        "replacing an open progress pathname is a POSIX-specific race probe",
    )
    def test_same_byte_progress_path_swap_after_open_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "training-progress.json"
            definition = self._definition()
            store = TrainingProgressStore(path)
            store.save(ExerciseSession(definition), expected_revision=None)
            original = path.read_bytes()
            replacement = root / "replacement-progress.json"
            replacement.write_bytes(original)

            real_open = progress_store_module._open_no_reparse
            swapped = False

            def racing_open(
                candidate: Path,
                *,
                create: bool,
                writable: bool = False,
                exclusive: bool = False,
            ) -> int:
                nonlocal swapped
                descriptor = real_open(
                    Path(candidate),
                    create=create,
                    writable=writable,
                    exclusive=exclusive,
                )
                if Path(candidate) == path and not create and not swapped:
                    swapped = True
                    os.replace(replacement, path)
                return descriptor

            with mock.patch(
                "acs.training_progress_store._open_no_reparse",
                side_effect=racing_open,
            ):
                with self.assertRaisesRegex(ValueError, "changed while being opened"):
                    TrainingProgressStore(path).load(definition)

            self.assertTrue(swapped)
            self.assertEqual(original, path.read_bytes())

    def test_same_byte_temp_substitution_at_replace_withholds_success(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "training-progress.json"
            definition = self._definition()
            store = TrainingProgressStore(path)
            initial_revision = store.save(
                ExerciseSession(definition),
                expected_revision=None,
            )
            advanced = ExerciseSession(definition)
            advanced.submit("e4")

            real_replace = progress_store_module._replace_published_path
            substituted = False

            def racing_replace(source: Path, destination: Path) -> None:
                nonlocal substituted
                source = Path(source)
                replacement = root / "same-byte-temp-substitute.bin"
                replacement.write_bytes(source.read_bytes())
                os.replace(replacement, source)
                substituted = True
                real_replace(source, Path(destination))

            with mock.patch(
                "acs.training_progress_store._replace_published_path",
                side_effect=racing_replace,
            ):
                with self.assertRaises(TrainingProgressDurabilityUnknownError) as raised:
                    store.save(
                        advanced,
                        expected_revision=initial_revision,
                    )

            self.assertTrue(substituted)
            loaded = TrainingProgressStore(path).load(definition)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(1, loaded.session.step_index)
            self.assertEqual(("e4",), loaded.session.accepted_path)
            self.assertEqual(loaded.revision, raised.exception.published_revision)

    def test_same_byte_post_publish_swap_withholds_success(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "training-progress.json"
            definition = self._definition()
            store = TrainingProgressStore(path)
            initial_revision = store.save(
                ExerciseSession(definition),
                expected_revision=None,
            )
            advanced = ExerciseSession(definition)
            advanced.submit("e4")

            real_sync = progress_store_module._sync_published_path
            swapped = False

            def racing_sync(candidate: Path) -> None:
                nonlocal swapped
                candidate = Path(candidate)
                replacement = root / "same-byte-post-publish.bin"
                replacement.write_bytes(candidate.read_bytes())
                os.replace(replacement, candidate)
                swapped = True
                real_sync(candidate)

            with mock.patch(
                "acs.training_progress_store._sync_published_path",
                side_effect=racing_sync,
            ):
                with self.assertRaises(TrainingProgressDurabilityUnknownError) as raised:
                    store.save(
                        advanced,
                        expected_revision=initial_revision,
                    )

            self.assertTrue(swapped)
            loaded = TrainingProgressStore(path).load(definition)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(1, loaded.session.step_index)
            self.assertEqual(("e4",), loaded.session.accepted_path)
            self.assertEqual(loaded.revision, raised.exception.published_revision)

    @unittest.skipIf(
        os.name == "nt",
        "replacing an open locked pathname is a POSIX-specific race probe",
    )
    def test_lock_path_swap_during_publication_withholds_success(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "training-progress.json"
            definition = self._definition()
            store = TrainingProgressStore(path)
            initial_revision = store.save(
                ExerciseSession(definition),
                expected_revision=None,
            )
            advanced = ExerciseSession(definition)
            advanced.submit("e4")

            real_replace = progress_store_module._replace_published_path
            swapped = False

            def racing_replace(source: Path, destination: Path) -> None:
                nonlocal swapped
                replacement_lock = root / "replacement-lock.bin"
                replacement_lock.write_bytes(b"\0")
                os.replace(replacement_lock, store._lock_path)
                swapped = True
                real_replace(Path(source), Path(destination))

            with mock.patch(
                "acs.training_progress_store._replace_published_path",
                side_effect=racing_replace,
            ):
                with self.assertRaises(TrainingProgressDurabilityUnknownError) as raised:
                    store.save(
                        advanced,
                        expected_revision=initial_revision,
                    )

            self.assertTrue(swapped)
            self.assertEqual(b"\0", store._lock_path.read_bytes())
            loaded = TrainingProgressStore(path).load(definition)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(1, loaded.session.step_index)
            self.assertEqual(loaded.revision, raised.exception.published_revision)

    def test_failed_temp_cleanup_never_unlinks_substituted_foreign_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "training-progress.json"
            definition = self._definition()
            store = TrainingProgressStore(path)
            initial_revision = store.save(
                ExerciseSession(definition),
                expected_revision=None,
            )
            original = path.read_bytes()
            advanced = ExerciseSession(definition)
            advanced.submit("e4")
            substituted_path: Path | None = None

            def fail_after_substitution(source: Path, destination: Path) -> None:
                nonlocal substituted_path
                candidate = Path(source)
                candidate.unlink()
                candidate.write_bytes(b"foreign-temp-bytes")
                substituted_path = candidate
                raise OSError("injected replace failure after temp substitution")

            with mock.patch(
                "acs.training_progress_store._replace_published_path",
                side_effect=fail_after_substitution,
            ):
                with self.assertRaisesRegex(OSError, "injected replace failure"):
                    store.save(
                        advanced,
                        expected_revision=initial_revision,
                    )

            self.assertIsNotNone(substituted_path)
            assert substituted_path is not None
            self.assertTrue(substituted_path.exists())
            self.assertEqual(b"foreign-temp-bytes", substituted_path.read_bytes())
            self.assertEqual(original, path.read_bytes())

    def test_failed_lock_initialization_vacates_only_owned_lock_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "training-progress.json"
            store = TrainingProgressStore(path)

            with mock.patch(
                "acs.training_progress_store.os.write",
                side_effect=OSError("injected lock marker failure"),
            ):
                with self.assertRaises(TrainingProgressBusyError):
                    store.save(
                        ExerciseSession(self._definition()),
                        expected_revision=None,
                    )

            self.assertFalse(store._lock_path.exists())
            self.assertFalse(path.exists())

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
