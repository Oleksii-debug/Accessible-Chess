from __future__ import annotations

import multiprocessing
from pathlib import Path
import queue
import tempfile
import unittest

from acs.student_progress import ReviewKind, StudentProgressLedger, StudentReviewRecord
from acs.student_progress_store import (
    StudentProgressBusyError,
    StudentProgressConflictError,
    StudentProgressStore,
)


def _seed_ledger() -> StudentProgressLedger:
    ledger = StudentProgressLedger()
    ledger.append(
        StudentReviewRecord(
            record_id="seed",
            student_id="student-1",
            session_id="session-1",
            kind=ReviewKind.GAME,
            source_id="game-seed",
            source_revision="rev-seed",
            sequence=1,
            attempts=0,
            mistakes=0,
            hints_used=0,
            completed=True,
        )
    )
    return ledger


def _peer_writer(
    path: str,
    label: str,
    barrier: object,
    result_queue: object,
) -> None:
    """Load one shared revision, synchronize, then attempt one peer publication."""

    store = StudentProgressStore(path)
    loaded = store.load()
    if loaded is None:
        result_queue.put(("error", label, "missing-seed"))  # type: ignore[attr-defined]
        return

    loaded.ledger.append(
        StudentReviewRecord(
            record_id=f"peer-{label}",
            student_id="student-1",
            session_id="session-1",
            kind=ReviewKind.GAME,
            source_id=f"game-{label}",
            source_revision=f"rev-{label}",
            sequence=2,
            attempts=0,
            mistakes=0,
            hints_used=0,
            completed=True,
        )
    )

    try:
        barrier.wait(timeout=20)  # type: ignore[attr-defined]
    except BaseException as exc:
        result_queue.put(("error", label, f"barrier:{type(exc).__name__}:{exc}"))  # type: ignore[attr-defined]
        return

    try:
        revision = store.save(
            loaded.ledger,
            expected_revision=loaded.revision,
        )
    except StudentProgressBusyError:
        result_queue.put(("busy", label, loaded.revision))  # type: ignore[attr-defined]
    except StudentProgressConflictError:
        result_queue.put(("conflict", label, loaded.revision))  # type: ignore[attr-defined]
    except BaseException as exc:
        result_queue.put(("error", label, f"save:{type(exc).__name__}:{exc}"))  # type: ignore[attr-defined]
    else:
        result_queue.put(("success", label, revision))  # type: ignore[attr-defined]


class D10ReviewProgressPeerCasTests(unittest.TestCase):
    def test_two_spawned_peers_cannot_silently_last_writer_win(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "student-progress.json"
            store = StudentProgressStore(path)
            initial_revision = store.save(_seed_ledger(), expected_revision=None)

            context = multiprocessing.get_context("spawn")
            barrier = context.Barrier(2)
            result_queue = context.Queue()
            processes = [
                context.Process(
                    target=_peer_writer,
                    args=(str(path), label, barrier, result_queue),
                    name=f"progress-peer-{label}",
                )
                for label in ("a", "b")
            ]

            for process in processes:
                process.start()
            for process in processes:
                process.join(timeout=30)

            for process in processes:
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)
                    self.fail(f"peer process did not finish: {process.name}")
                self.assertEqual(process.exitcode, 0, process.name)

            results: list[tuple[str, str, str]] = []
            for _ in processes:
                try:
                    result = result_queue.get(timeout=5)
                except queue.Empty as exc:
                    self.fail("peer process produced no result")
                    raise AssertionError from exc
                self.assertIsInstance(result, tuple)
                self.assertEqual(len(result), 3)
                results.append(result)

            errors = [result for result in results if result[0] == "error"]
            self.assertEqual(errors, [], results)

            successes = [result for result in results if result[0] == "success"]
            losers = [result for result in results if result[0] in {"busy", "conflict"}]
            self.assertEqual(len(successes), 1, results)
            self.assertEqual(len(losers), 1, results)

            winner_status, winner_label, winning_revision = successes[0]
            self.assertEqual(winner_status, "success")
            self.assertNotEqual(winning_revision, initial_revision)

            loser_status, loser_label, loser_observed_revision = losers[0]
            self.assertIn(loser_status, {"busy", "conflict"})
            self.assertNotEqual(winner_label, loser_label)
            self.assertEqual(loser_observed_revision, initial_revision)

            reopened = StudentProgressStore(path).load()
            self.assertIsNotNone(reopened)
            assert reopened is not None
            self.assertEqual(reopened.revision, winning_revision)
            self.assertEqual(
                [
                    record.record_id
                    for record in reopened.ledger.records("student-1", "session-1")
                ],
                ["seed", f"peer-{winner_label}"],
            )
            self.assertFalse(
                any(
                    record.record_id == f"peer-{loser_label}"
                    for record in reopened.ledger.records("student-1", "session-1")
                )
            )
            self.assertFalse(store._lock_path.exists())

            result_queue.close()
            result_queue.join_thread()


if __name__ == "__main__":
    unittest.main()
