from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.pgn_document import PgnDocumentSession
from acs.pgn_save_snapshot import (
    PgnSaveCancelledError,
    PgnSaveMode,
    capture_pgn_save_snapshot,
    commit_pgn_save_publication,
    expected_pgn_destination_sha256,
    publish_pgn_save_snapshot,
)


ONE_GAME = '''[Event "Original"]
[White "Alpha"]
[Black "Beta"]
[Result "*"]

1. e4 e5 *
'''

TWO_GAMES = ONE_GAME + '''
[Event "Second"]
[White "Gamma"]
[Black "Delta"]
[Result "*"]

1. d4 d5 *
'''


class PgnSaveSnapshotCancellationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_cancel_at_canonical_pre_publish_gate_leaves_source_unchanged(self) -> None:
        source = self.root / "source.pgn"
        source.write_text(ONE_GAME, encoding="utf-8", newline="\n")
        original_bytes = source.read_bytes()
        session = PgnDocumentSession.open(source)
        session.edit_tag("Event", "Pending Save")
        snapshot = capture_pgn_save_snapshot(session, mode=PgnSaveMode.SAVE)

        calls = 0

        def cancel_check() -> bool:
            nonlocal calls
            calls += 1
            # one pre-worker poll, one post-revalidation poll, one per-game
            # poll, then the canonical save_pgn_atomic pre_publish_check.
            return calls >= 4

        with self.assertRaises(PgnSaveCancelledError):
            publish_pgn_save_snapshot(snapshot, cancel_check=cancel_check)

        self.assertEqual(source.read_bytes(), original_bytes)
        self.assertTrue(session.dirty)
        self.assertIn("Pending Save", session.copy_pgn())
        self.assertEqual(session.source, snapshot.source_before)
        self.assertEqual(calls, 4)

    def test_cancel_between_games_removes_unpublished_temp_and_destination(self) -> None:
        session = PgnDocumentSession.from_text(TWO_GAMES)
        snapshot = capture_pgn_save_snapshot(session, mode=PgnSaveMode.SAVE_AS)
        target = self.root / "cancelled-two-games.pgn"
        calls = 0

        def cancel_check() -> bool:
            nonlocal calls
            calls += 1
            # Cancel on the second record poll, before flush/fsync/publication.
            return calls >= 4

        with self.assertRaises(PgnSaveCancelledError):
            publish_pgn_save_snapshot(
                snapshot,
                path=target,
                cancel_check=cancel_check,
            )

        self.assertFalse(target.exists())
        self.assertIsNone(session.source)
        self.assertTrue(session.dirty)

    def test_cancel_during_destination_hash_stops_between_chunks(self) -> None:
        target = self.root / "existing-large.pgn"
        original = b"x" * (3 * 1024 * 1024 + 17)
        target.write_bytes(original)
        calls = 0

        def cancel_check() -> bool:
            nonlocal calls
            calls += 1
            # Helper preflight + fingerprint entry + first 1 MiB read are
            # permitted. The next chunk poll must stop the first hash pass,
            # rather than waiting for both complete fingerprint passes.
            return calls >= 4

        with self.assertRaises(PgnSaveCancelledError):
            expected_pgn_destination_sha256(target, cancel_check=cancel_check)

        self.assertEqual(calls, 4)
        self.assertEqual(target.read_bytes(), original)

    def test_cancel_arriving_after_publication_cannot_turn_success_into_cancel(self) -> None:
        session = PgnDocumentSession.from_text(ONE_GAME)
        snapshot = capture_pgn_save_snapshot(session, mode=PgnSaveMode.SAVE_AS)
        target = self.root / "durable-success.pgn"
        cancelled = False
        calls = 0

        def cancel_check() -> bool:
            nonlocal calls
            calls += 1
            return cancelled

        publication = publish_pgn_save_snapshot(
            snapshot,
            path=target,
            cancel_check=cancel_check,
        )
        self.assertTrue(target.exists())
        polls_at_publication = calls

        # The atomic writer has already returned durable success. Owner commit
        # deliberately has no cancellation argument/poll and must publish that
        # success even if Cancel is requested immediately afterwards.
        cancelled = True
        view = commit_pgn_save_publication(session, publication)
        self.assertEqual(calls, polls_at_publication)
        self.assertFalse(view.dirty)
        self.assertEqual(session.source, publication.saved)

    def test_non_boolean_cancel_result_fails_closed_before_publication(self) -> None:
        session = PgnDocumentSession.from_text(ONE_GAME)
        snapshot = capture_pgn_save_snapshot(session, mode=PgnSaveMode.SAVE_AS)
        target = self.root / "invalid-cancel.pgn"

        with self.assertRaises(TypeError):
            publish_pgn_save_snapshot(
                snapshot,
                path=target,
                cancel_check=lambda: 1,  # type: ignore[return-value]
            )
        self.assertFalse(target.exists())
        self.assertIsNone(session.source)


if __name__ == "__main__":
    unittest.main()
