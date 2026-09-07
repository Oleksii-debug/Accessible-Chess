from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.gametree import CanonicalPgnGameFramer
from acs.library_import_service import LibraryImportService
from acs.pgn_roundtrip import (
    PgnRoundTripError,
    PgnRoundTripErrorCode,
    parse_pgn_text,
    serialize_pgn_text,
)
from acs.pgn_streaming_import import (
    StreamingPgnErrorCode,
    StreamingPgnFailurePolicy,
    StreamingPgnImportError,
    StreamingPgnLibraryImporter,
    StreamingPgnLimits,
)


NESTED_MULTILINE_TAGLIKE_COMMENT = '''[Event "Outer game"]
[Result "*"]

1. e4 {outer line
inner {K. B.}
[Site "comment metadata"]
tail} e5 *
'''


class W1D06NestedCommentFramerConvergenceTests(unittest.TestCase):
    def _frames(self, source: str):
        framer = CanonicalPgnGameFramer()
        frames = []
        for line in source.split("\n"):
            completed = framer.feed_line(line)
            if completed is not None:
                frames.append(completed)
        completed = framer.finish()
        if completed is not None:
            frames.append(completed)
        return frames

    def test_canonical_framer_keeps_taglike_line_inside_recovered_outer_comment(self) -> None:
        frames = self._frames(NESTED_MULTILINE_TAGLIKE_COMMENT)

        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].tags["Event"], "Outer game")
        self.assertNotIn("Site", frames[0].tags)
        self.assertIn('[Site "comment metadata"]', frames[0].movetext)

    def test_recovery_round_trip_preserves_taglike_text_as_comment_not_new_game(self) -> None:
        games = parse_pgn_text(NESTED_MULTILINE_TAGLIKE_COMMENT, strict=False)
        self.assertEqual(len(games), 1)
        game = games[0]
        self.assertEqual(game.tags["Event"], "Outer game")
        self.assertNotIn("Site", game.tags)
        self.assertEqual(
            game.warnings,
            ["nested brace comment delimiters normalized to parentheses"],
        )
        self.assertEqual([move.san for move in game.line.moves], ["e4", "e5"])
        comment = game.line.moves[0].comments_after[0].text
        self.assertIn("inner (K. B.)", comment)
        self.assertIn('[Site "comment metadata"]', comment)
        self.assertTrue(comment.rstrip().endswith("tail"))

        canonical = serialize_pgn_text(games)
        reopened = parse_pgn_text(canonical, strict=True)
        self.assertEqual(len(reopened), 1)
        self.assertEqual(reopened[0].tags, game.tags)
        self.assertEqual(reopened[0].line, game.line)
        self.assertFalse(reopened[0].warnings)

    def test_strict_mode_still_rejects_nested_comment_recovery(self) -> None:
        with self.assertRaises(PgnRoundTripError) as caught:
            parse_pgn_text(NESTED_MULTILINE_TAGLIKE_COMMENT, strict=True)
        self.assertEqual(caught.exception.code, PgnRoundTripErrorCode.MALFORMED_PGN)

    def test_streaming_prefix_policy_cannot_publish_false_nested_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory, AcsDatabase() as database:
            source = Path(directory) / "nested-taglike-comment.pgn"
            source.write_text(
                NESTED_MULTILINE_TAGLIKE_COMMENT,
                encoding="utf-8",
                newline="",
            )
            importer = StreamingPgnLibraryImporter(LibraryImportService(database))

            with self.assertRaises(StreamingPgnImportError) as caught:
                importer.import_file(
                    source,
                    failure_policy=StreamingPgnFailurePolicy.COMMIT_ACCEPTED_PREFIX,
                    limits=StreamingPgnLimits(read_chunk_bytes=7),
                )

            self.assertEqual(caught.exception.code, StreamingPgnErrorCode.MALFORMED_PGN)
            self.assertEqual(caught.exception.semantic_code, "pgn_malformed_pgn")
            self.assertEqual(caught.exception.accepted_games, 0)
            self.assertEqual(database.search_games(limit=10), [])

    def test_literal_opening_brace_legacy_case_allows_later_result_and_next_game(self) -> None:
        source = (
            '[Event "First"]\n[Result "*"]\n\n'
            '1. e4 {{ editorial opener} e5\n'
            '*\n'
            '[Event "Second"]\n[Result "*"]\n\n1. d4 d5 *\n'
        )
        frames = self._frames(source)
        self.assertEqual(
            [frame.tags["Event"] for frame in frames],
            ["First", "Second"],
        )

        games = parse_pgn_text(source, strict=True)
        self.assertEqual([game.tags["Event"] for game in games], ["First", "Second"])
        self.assertEqual(
            games[0].line.moves[0].comments_after[0].text,
            "{ editorial opener",
        )


if __name__ == "__main__":
    unittest.main()
