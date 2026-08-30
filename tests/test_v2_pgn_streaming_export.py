from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import acs.pgn_service as pgn_service
from acs.gametree import PgnGame, serialize_games
from acs.pgn_roundtrip import parse_pgn_text


_SAMPLE = """[Event \"One\"]
[Result \"1-0\"]

1. e4 e5 2. Nf3 Nc6 1-0

[Event \"Два\"]
[SetUp \"1\"]
[FEN \"4k3/8/8/8/8/8/4K3/8 w - - 0 1\"]
[Result \"*\"]

1. Kf3 {коментар} Ke7 $1 *
"""


class V2PgnStreamingExportTests(unittest.TestCase):
    def _games(self) -> tuple[PgnGame, ...]:
        return parse_pgn_text(_SAMPLE, strict=False)

    def test_export_consumes_and_serializes_one_game_before_requesting_next(self) -> None:
        games = self._games()
        serialized: list[int] = []
        original = pgn_service.serialize_game

        def observed(game: PgnGame) -> str:
            serialized.append(game.source_index)
            return original(game)

        def source():
            yield games[0]
            # Eager tuple(games) materialization resumes the generator before
            # the first game has been serialized and therefore fails here.
            self.assertEqual(serialized, [games[0].source_index])
            yield games[1]

        with tempfile.TemporaryDirectory() as raw_dir:
            destination = Path(raw_dir) / "партії з пробілом.pgn"
            pgn_service.serialize_game = observed
            try:
                pgn_service.save_pgn_atomic(destination, source())
            finally:
                pgn_service.serialize_game = original

            self.assertEqual(serialized, [game.source_index for game in games])
            self.assertEqual(destination.read_text(encoding="utf-8"), serialize_games(games))

    def test_incremental_export_is_byte_identical_to_canonical_serializer(self) -> None:
        games = self._games()
        expected = serialize_games(games).encode("utf-8")
        with tempfile.TemporaryDirectory() as raw_dir:
            destination = Path(raw_dir) / "round trip.pgn"
            result = pgn_service.save_pgn_atomic(destination, iter(games))
            self.assertEqual(destination.read_bytes(), expected)
            self.assertEqual(result.size, len(expected))

    def test_late_iterator_failure_preserves_existing_destination_and_cleans_temp(self) -> None:
        games = self._games()

        class LateFailure(RuntimeError):
            pass

        def source():
            yield games[0]
            raise LateFailure("synthetic late producer failure")

        with tempfile.TemporaryDirectory() as raw_dir:
            directory = Path(raw_dir)
            destination = directory / "existing.pgn"
            original = b"existing bytes\n"
            destination.write_bytes(original)

            with self.assertRaises(LateFailure):
                pgn_service.save_pgn_atomic(destination, source(), overwrite=True)

            self.assertEqual(destination.read_bytes(), original)
            self.assertEqual(list(directory.glob(destination.name + ".*.tmp")), [])

    def test_empty_iterable_preserves_empty_canonical_document(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            destination = Path(raw_dir) / "empty.pgn"
            pgn_service.save_pgn_atomic(destination, iter(()))
            self.assertEqual(destination.read_bytes(), b"")


if __name__ == "__main__":
    unittest.main()
