from __future__ import annotations

import hashlib
import json
import multiprocessing
from pathlib import Path
import tempfile
import time
import unittest

from acs.chesscore import Board
from acs.training import ExerciseDefinition, ExerciseSession, ExerciseStep
from acs.training_progress_store import (
    MAX_TRAINING_PROGRESS_BYTES,
    TrainingProgressBusyError,
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
            definition = ExerciseDefinition(
                "x" * (MAX_TRAINING_PROGRESS_BYTES + 1),
                Board.START,
                (ExerciseStep(frozenset({"e4"})),),
            )
            store = TrainingProgressStore(path)

            with self.assertRaises(TrainingProgressResourceError):
                store.save(ExerciseSession(definition), expected_revision=None)
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
            with self.assertRaisesRegex(ValueError, "not a regular file"):
                store.load(self._definition())
            with self.assertRaisesRegex(ValueError, "not a regular file"):
                store.save(
                    ExerciseSession(self._definition()),
                    expected_revision=None,
                )
            self.assertEqual("outside-user-data", target.read_text(encoding="utf-8"))
            self.assertTrue(path.is_symlink())


if __name__ == "__main__":
    unittest.main()
