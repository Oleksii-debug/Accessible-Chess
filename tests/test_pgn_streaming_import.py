from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.gametree import CanonicalPgnGameFramer, _split_games, serialize_game
from acs.library_import_service import LibraryImportService
from acs.pgn_roundtrip import PgnRoundTripError, PgnRoundTripErrorCode, parse_pgn_text
from acs.pgn_streaming_import import (
    StreamingPgnErrorCode,
    StreamingPgnFailurePolicy,
    StreamingPgnImportCancelledError,
    StreamingPgnImportError,
    StreamingPgnLimits,
    StreamingPgnPhase,
    StreamingPgnLibraryImporter,
)


RICH_TWO_GAME_PGN = '''[Event "Nested – Київ ♟"]
[White "Аліса"]
[Black "Bob"]
[Result "*"]

1. e4 {main український
[Event "comment text, not a game"]
continued} e5 (1... c5 $1 {Sicilian} 2. Nf3 (2. Nc3 Nc6)) 2. Nf3 Nc6 *

[Event "SetUp – Café"]
[SetUp "1"]
[FEN "8/8/8/8/8/8/4K3/7k w - - 0 1"]
[Result "*"]

*
'''

GOOD_PREFIX_THEN_TRUNCATED = '''[Event "Accepted"]
[Result "*"]

1. e4 e5 *

[Event "Broken"]
[Result "*"]

1. d4 {unterminated
'''

MALFORMED_HEADER_AFTER_COMPLETE_GAME = '''[Event "First"]
[Result "*"]

1. e4 e5 *

[this is not a tag pair
[Event "Second"]
[Result "*"]

1. d4 d5 *
'''

BOUNDARY_EQUIVALENCE_PGN = r'''[Event "Escaped \" title"]
[Site "Київ"]
[Result "*"]

1. e4 {multiline
[Event "inside comment, not a boundary"]
continued} e5 *

[Event "Second"]
[Result "*"]

1. d4 ; [Event "semicolon text"]
d5 *
'''


def tiny_chunks(
    *,
    max_games: int = 100,
    max_source_bytes: int = 1_000_000,
    max_text_chars: int = 1_000_000,
    max_lexical_tokens: int = 100_000,
) -> StreamingPgnLimits:
    return StreamingPgnLimits(
        read_chunk_bytes=1,
        max_source_bytes=max_source_bytes,
        max_text_chars=max_text_chars,
        max_lexical_tokens=max_lexical_tokens,
        max_game_bytes=1_000_000,
        max_spool_bytes=2_000_000,
        max_games=max_games,
    )


class StreamingPgnImportTests(unittest.TestCase):
    def _new_importer(self, database: AcsDatabase) -> StreamingPgnLibraryImporter:
        return StreamingPgnLibraryImporter(LibraryImportService(database))

    def test_incremental_unicode_nested_rav_nag_fen_library_reopen_export_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as directory, AcsDatabase() as database:
            source = Path(directory) / "rich.pgn"
            source.write_text(RICH_TWO_GAME_PGN, encoding="utf-8", newline="")
            progress = []

            result = self._new_importer(database).import_file(
                source,
                failure_policy=StreamingPgnFailurePolicy.SOURCE_ATOMIC,
                limits=tiny_chunks(),
                progress_callback=progress.append,
            )

            self.assertTrue(result.complete)
            self.assertEqual(result.accepted_games, 2)
            self.assertEqual(result.library.game_count, 2)
            self.assertEqual(result.library.warning_count, 0)
            self.assertEqual(
                {item.phase for item in progress},
                {StreamingPgnPhase.PARSING, StreamingPgnPhase.IMPORTING},
            )
            self.assertEqual(progress[-1].imported_games, 2)
            self.assertEqual(progress[-1].total_games, 2)

            first_row = database.get_game(result.library.first_game_id)
            second_row = database.get_game(result.library.last_game_id)
            self.assertIsNotNone(first_row)
            self.assertIsNotNone(second_row)
            assert first_row is not None and second_row is not None

            first = parse_pgn_text(first_row["pgn_text"], strict=True)[0]
            self.assertEqual(first.tags["Event"], "Nested – Київ ♟")
            self.assertEqual(first.tags["White"], "Аліса")
            self.assertEqual(first.line.moves[0].comments_after[0].text, (
                'main український\n[Event "comment text, not a game"]\ncontinued'
            ))
            variation = first.line.moves[1].variations[0]
            self.assertIn("$1", variation.moves[0].nags)
            self.assertEqual(
                [move.san for move in variation.moves[1].variations[0].moves],
                ["Nc3", "Nc6"],
            )

            second = parse_pgn_text(second_row["pgn_text"], strict=True)[0]
            self.assertEqual(second.tags["SetUp"], "1")
            self.assertEqual(second.tags["FEN"], "8/8/8/8/8/8/4K3/7k w - - 0 1")
            self.assertEqual(second.tags["Event"], "SetUp – Café")

            # Canonical Library reopen -> export sample -> reopen must be stable.
            for row in (first_row, second_row):
                stored = parse_pgn_text(row["pgn_text"], strict=True)[0]
                exported = serialize_game(stored)
                reopened = parse_pgn_text(exported, strict=True)[0]
                self.assertEqual(serialize_game(reopened), exported)

    def test_streaming_and_whole_text_share_exact_boundary_state_machine(self) -> None:
        framer = CanonicalPgnGameFramer()
        frames = []
        for line in BOUNDARY_EQUIVALENCE_PGN.split("\n"):
            completed = framer.feed_line(line)
            if completed is not None:
                frames.append(completed)
        completed = framer.finish()
        if completed is not None:
            frames.append(completed)

        self.assertEqual(
            [(frame.tags, frame.movetext, list(frame.warnings)) for frame in frames],
            _split_games(BOUNDARY_EQUIVALENCE_PGN),
        )
        whole = parse_pgn_text(BOUNDARY_EQUIVALENCE_PGN, strict=True)
        self.assertEqual(len(whole), 2)
        self.assertEqual(whole[0].tags["Event"], 'Escaped " title')
        self.assertIn(
            '[Event "inside comment, not a boundary"]',
            whole[0].line.moves[0].comments_after[0].text,
        )

        with tempfile.TemporaryDirectory() as directory, AcsDatabase() as database:
            source = Path(directory) / "boundaries.pgn"
            source.write_text(BOUNDARY_EQUIVALENCE_PGN, encoding="utf-8", newline="")
            result = self._new_importer(database).import_file(
                source,
                failure_policy=StreamingPgnFailurePolicy.SOURCE_ATOMIC,
                limits=tiny_chunks(),
            )
            stored = []
            for game_id in range(
                result.library.first_game_id,
                result.library.last_game_id + 1,
            ):
                row = database.get_game(game_id)
                self.assertIsNotNone(row)
                assert row is not None
                stored.append(parse_pgn_text(row["pgn_text"], strict=True)[0])
            self.assertEqual(
                [serialize_game(game) for game in stored],
                [serialize_game(game) for game in whole],
            )

    def test_malformed_open_bracket_cannot_publish_a_divergent_prefix(self) -> None:
        with self.assertRaises(PgnRoundTripError) as whole_failure:
            parse_pgn_text(MALFORMED_HEADER_AFTER_COMPLETE_GAME, strict=True)
        self.assertEqual(
            whole_failure.exception.code,
            PgnRoundTripErrorCode.MALFORMED_HEADER,
        )

        with tempfile.TemporaryDirectory() as directory, AcsDatabase() as database:
            source = Path(directory) / "malformed-boundary.pgn"
            source.write_text(
                MALFORMED_HEADER_AFTER_COMPLETE_GAME,
                encoding="utf-8",
                newline="",
            )
            with self.assertRaises(StreamingPgnImportError) as caught:
                self._new_importer(database).import_file(
                    source,
                    failure_policy=StreamingPgnFailurePolicy.COMMIT_ACCEPTED_PREFIX,
                    limits=tiny_chunks(),
                )
            self.assertEqual(caught.exception.code, StreamingPgnErrorCode.MALFORMED_PGN)
            self.assertEqual(caught.exception.semantic_code, "pgn_malformed_header")
            self.assertEqual(caught.exception.accepted_games, 0)
            self.assertEqual(database.search_games(limit=100), [])

    def test_duplicate_tag_recovery_surface_is_equivalent_and_atomic(self) -> None:
        source_text = '''[Event "One"]
[Event "Duplicate"]
[Result "*"]

1. e4 *
'''
        with self.assertRaises(PgnRoundTripError) as whole_failure:
            parse_pgn_text(source_text, strict=True)
        self.assertEqual(
            whole_failure.exception.code,
            PgnRoundTripErrorCode.MALFORMED_PGN,
        )

        with tempfile.TemporaryDirectory() as directory, AcsDatabase() as database:
            source = Path(directory) / "duplicate-tag.pgn"
            source.write_text(source_text, encoding="utf-8", newline="")
            with self.assertRaises(StreamingPgnImportError) as caught:
                self._new_importer(database).import_file(
                    source,
                    failure_policy=StreamingPgnFailurePolicy.COMMIT_ACCEPTED_PREFIX,
                    limits=tiny_chunks(),
                )
            self.assertEqual(caught.exception.semantic_code, "pgn_malformed_pgn")
            self.assertEqual(database.search_games(limit=100), [])

    def test_global_text_token_and_game_budgets_never_reset_per_frame(self) -> None:
        source_text = (
            '[Event "One"]\n[Result "*"]\n\n1. e4 e5 *\n\n'
            '[Event "Two"]\n[Result "*"]\n\n1. d4 d5 *\n'
        )
        cases = (
            (
                "text",
                tiny_chunks(max_text_chars=60),
                StreamingPgnErrorCode.TEXT_SIZE_LIMIT,
            ),
            (
                "tokens",
                tiny_chunks(max_lexical_tokens=8),
                StreamingPgnErrorCode.TOKEN_COUNT_LIMIT,
            ),
            (
                "games",
                tiny_chunks(max_games=1),
                StreamingPgnErrorCode.GAME_COUNT_LIMIT,
            ),
        )
        for name, limits, expected_code in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory, AcsDatabase() as database:
                source = Path(directory) / f"global-{name}.pgn"
                source.write_text(source_text, encoding="utf-8", newline="")
                with self.assertRaises(StreamingPgnImportError) as caught:
                    self._new_importer(database).import_file(
                        source,
                        failure_policy=StreamingPgnFailurePolicy.COMMIT_ACCEPTED_PREFIX,
                        limits=limits,
                    )
                self.assertEqual(caught.exception.code, expected_code)
                self.assertEqual(database.search_games(limit=100), [])

    def test_atomic_policy_rejects_later_truncation_without_losing_evidence_or_publishing_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as directory, AcsDatabase() as database:
            source = Path(directory) / "truncated.pgn"
            source.write_text(GOOD_PREFIX_THEN_TRUNCATED, encoding="utf-8")

            with self.assertRaises(StreamingPgnImportError) as caught:
                self._new_importer(database).import_file(
                    source,
                    failure_policy=StreamingPgnFailurePolicy.SOURCE_ATOMIC,
                    limits=tiny_chunks(),
                )

            self.assertEqual(caught.exception.code, StreamingPgnErrorCode.TRUNCATED_PGN)
            self.assertEqual(caught.exception.accepted_games, 1)
            self.assertEqual(database.search_games(limit=100), [])

    def test_explicit_prefix_policy_commits_accepted_game_after_later_truncation(self) -> None:
        with tempfile.TemporaryDirectory() as directory, AcsDatabase() as database:
            source = Path(directory) / "truncated.pgn"
            source.write_text(GOOD_PREFIX_THEN_TRUNCATED, encoding="utf-8")

            result = self._new_importer(database).import_file(
                source,
                failure_policy=StreamingPgnFailurePolicy.COMMIT_ACCEPTED_PREFIX,
                limits=tiny_chunks(),
            )

            self.assertFalse(result.complete)
            self.assertEqual(result.accepted_games, 1)
            self.assertEqual(result.library.game_count, 1)
            self.assertEqual(result.library.warning_count, 1)
            self.assertEqual(result.failure_code, "pgn_truncated_comment")
            row = database.get_game(result.library.first_game_id)
            self.assertIsNotNone(row)
            assert row is not None
            reopened = parse_pgn_text(row["pgn_text"], strict=True)[0]
            self.assertEqual(reopened.tags["Event"], "Accepted")

    def test_invalid_utf8_is_distinct_and_atomic(self) -> None:
        with tempfile.TemporaryDirectory() as directory, AcsDatabase() as database:
            source = Path(directory) / "invalid-encoding.pgn"
            source.write_bytes(b'[Event "Bad"]\n[Result "*"]\n\n1. e4 ' + b'\xff' + b' *\n')

            with self.assertRaises(StreamingPgnImportError) as caught:
                self._new_importer(database).import_file(
                    source,
                    failure_policy=StreamingPgnFailurePolicy.SOURCE_ATOMIC,
                    limits=tiny_chunks(),
                )

            self.assertEqual(caught.exception.code, StreamingPgnErrorCode.INVALID_ENCODING)
            self.assertEqual(database.search_games(limit=100), [])

    def test_cancellation_after_first_accepted_game_never_publishes_spool(self) -> None:
        with tempfile.TemporaryDirectory() as directory, AcsDatabase() as database:
            source = Path(directory) / "cancel.pgn"
            source.write_text(RICH_TWO_GAME_PGN, encoding="utf-8")
            cancel = {"requested": False}

            def on_progress(progress) -> None:
                if progress.phase is StreamingPgnPhase.PARSING and progress.accepted_games >= 1:
                    cancel["requested"] = True

            def cancelled() -> bool:
                return cancel["requested"]

            with self.assertRaises(StreamingPgnImportCancelledError) as caught:
                self._new_importer(database).import_file(
                    source,
                    failure_policy=StreamingPgnFailurePolicy.COMMIT_ACCEPTED_PREFIX,
                    limits=tiny_chunks(),
                    cancel_check=cancelled,
                    progress_callback=on_progress,
                )

            self.assertGreaterEqual(caught.exception.accepted_games, 1)
            self.assertEqual(database.search_games(limit=100), [])

    def test_source_change_during_stream_fails_closed_before_library_publication(self) -> None:
        with tempfile.TemporaryDirectory() as directory, AcsDatabase() as database:
            source = Path(directory) / "mutable.pgn"
            source.write_text(RICH_TWO_GAME_PGN, encoding="utf-8")
            changed = {"done": False}

            def mutate_after_first(progress) -> None:
                if (
                    progress.phase is StreamingPgnPhase.PARSING
                    and progress.accepted_games >= 1
                    and not changed["done"]
                ):
                    changed["done"] = True
                    with source.open("ab") as handle:
                        handle.write(b"\n; changed after fingerprint\n")

            with self.assertRaises(StreamingPgnImportError) as caught:
                self._new_importer(database).import_file(
                    source,
                    failure_policy=StreamingPgnFailurePolicy.COMMIT_ACCEPTED_PREFIX,
                    limits=tiny_chunks(),
                    progress_callback=mutate_after_first,
                )

            self.assertEqual(caught.exception.code, StreamingPgnErrorCode.SOURCE_CHANGED)
            self.assertEqual(database.search_games(limit=100), [])

    def test_source_size_game_count_and_spool_limits_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "limits.pgn"
            source.write_text(RICH_TWO_GAME_PGN, encoding="utf-8")

            with self.subTest(limit="source"):
                with AcsDatabase() as database:
                    with self.assertRaises(StreamingPgnImportError) as caught:
                        self._new_importer(database).import_file(
                            source,
                            failure_policy=StreamingPgnFailurePolicy.SOURCE_ATOMIC,
                            limits=tiny_chunks(max_source_bytes=10),
                        )
                    self.assertEqual(caught.exception.code, StreamingPgnErrorCode.SOURCE_SIZE_LIMIT)
                    self.assertEqual(database.search_games(limit=100), [])

            with self.subTest(limit="game-count"):
                with AcsDatabase() as database:
                    with self.assertRaises(StreamingPgnImportError) as caught:
                        self._new_importer(database).import_file(
                            source,
                            failure_policy=StreamingPgnFailurePolicy.SOURCE_ATOMIC,
                            limits=tiny_chunks(max_games=1),
                        )
                    self.assertEqual(caught.exception.code, StreamingPgnErrorCode.GAME_COUNT_LIMIT)
                    self.assertEqual(database.search_games(limit=100), [])

            with self.subTest(limit="spool"):
                with AcsDatabase() as database:
                    limits = StreamingPgnLimits(
                        read_chunk_bytes=1,
                        max_source_bytes=1_000_000,
                        max_game_bytes=1_000_000,
                        max_spool_bytes=10,
                        max_games=100,
                    )
                    with self.assertRaises(StreamingPgnImportError) as caught:
                        self._new_importer(database).import_file(
                            source,
                            failure_policy=StreamingPgnFailurePolicy.SOURCE_ATOMIC,
                            limits=limits,
                        )
                    self.assertEqual(caught.exception.code, StreamingPgnErrorCode.SPOOL_SIZE_LIMIT)
                    self.assertEqual(database.search_games(limit=100), [])

    def test_failure_policy_is_required_and_callbacks_are_strict(self) -> None:
        with tempfile.TemporaryDirectory() as directory, AcsDatabase() as database:
            source = Path(directory) / "one.pgn"
            source.write_text('[Event "One"]\n[Result "*"]\n\n1. e4 *\n', encoding="utf-8")
            importer = self._new_importer(database)

            with self.assertRaises(TypeError):
                importer.import_file(  # type: ignore[call-arg]
                    source,
                    limits=tiny_chunks(),
                )
            with self.assertRaises(TypeError):
                importer.import_file(
                    source,
                    failure_policy=StreamingPgnFailurePolicy.SOURCE_ATOMIC,
                    limits=tiny_chunks(),
                    cancel_check="no",  # type: ignore[arg-type]
                )
            with self.assertRaises(TypeError):
                importer.import_file(
                    source,
                    failure_policy=StreamingPgnFailurePolicy.SOURCE_ATOMIC,
                    limits=tiny_chunks(),
                    progress_callback=42,  # type: ignore[arg-type]
                )
            self.assertEqual(database.search_games(limit=100), [])


if __name__ == "__main__":
    unittest.main()
