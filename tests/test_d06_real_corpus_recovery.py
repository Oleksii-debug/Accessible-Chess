from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.pgn_document import (
    PgnDocumentError,
    PgnDocumentErrorCode,
    PgnDocumentSession,
)
from acs.pgn_workspace import PgnWorkspaceError


# Synthetic minimal equivalent of the real Lichess broadcast failure found by
# PGN-03.  The real corpus record is not copied into the repository.
DAMAGED_RESULT_PLACEHOLDER = '''[Event "Damaged broadcast placeholder"]
[Site "?"]
[Result "0-0"]
[Variant "Standard"]

0-0
'''


class D06RealCorpusRecoveryTests(unittest.TestCase):
    def test_invalid_result_shaped_terminal_token_recovers_without_touching_original(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "damaged.pgn"
            original = DAMAGED_RESULT_PLACEHOLDER.encode("utf-8")
            source.write_bytes(original)

            session = PgnDocumentSession.open(source)

            view = session.view()
            self.assertFalse(view.source_overwrite_safe)
            self.assertTrue(session.dirty)
            self.assertTrue(
                any("invalid header Result 0-0" in warning for warning in view.global_warnings)
            )
            self.assertTrue(
                any("recovered malformed result token 0-0" in warning for warning in view.global_warnings)
            )

            recovered = session.workspace.current_game()
            self.assertEqual(recovered.tags["Result"], "*")
            self.assertEqual(recovered.line.result, "*")
            self.assertEqual(recovered.line.moves, [])

            with self.assertRaises(PgnDocumentError) as caught:
                session.save()
            self.assertEqual(
                caught.exception.code,
                PgnDocumentErrorCode.SOURCE_REQUIRES_SAVE_AS,
            )
            self.assertEqual(source.read_bytes(), original)

            destination = root / "recovered.pgn"
            session.save_as(destination)
            self.assertEqual(source.read_bytes(), original)

            reopened = PgnDocumentSession.open(destination)
            reopened_view = reopened.view()
            self.assertTrue(reopened_view.source_overwrite_safe)
            self.assertFalse(reopened_view.global_warnings)
            canonical = reopened.workspace.current_game()
            self.assertEqual(canonical.tags["Result"], "*")
            self.assertEqual(canonical.line.result, "*")
            self.assertEqual(canonical.line.moves, [])

    def test_invalid_result_placeholder_does_not_hide_other_movetext(self) -> None:
        damaged = '''[Event "Not placeholder only"]
[Result "0-0"]

1. e4 0-0
'''
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "damaged.pgn"
            source.write_text(damaged, encoding="utf-8")
            with self.assertRaises(PgnWorkspaceError):
                PgnDocumentSession.open(source)

    def test_valid_header_result_does_not_reclassify_invalid_san(self) -> None:
        damaged = '''[Event "Valid header"]
[Result "*"]

0-0
'''
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "damaged.pgn"
            source.write_text(damaged, encoding="utf-8")
            with self.assertRaises(PgnWorkspaceError):
                PgnDocumentSession.open(source)

    def test_invalid_header_must_match_the_only_movetext_token(self) -> None:
        damaged = '''[Event "Mismatch"]
[Result "0-0"]

1-1
'''
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "damaged.pgn"
            source.write_text(damaged, encoding="utf-8")
            with self.assertRaises(PgnWorkspaceError):
                PgnDocumentSession.open(source)

    def test_comments_make_result_placeholder_recovery_ambiguous(self) -> None:
        damaged = '''[Event "Commented"]
[Result "0-0"]

{source note} 0-0
'''
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "damaged.pgn"
            source.write_text(damaged, encoding="utf-8")
            with self.assertRaises(PgnWorkspaceError):
                PgnDocumentSession.open(source)


if __name__ == "__main__":
    unittest.main()
