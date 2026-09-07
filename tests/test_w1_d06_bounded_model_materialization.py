from __future__ import annotations

import unittest
from unittest import mock

import acs.pgn_roundtrip as pgn_roundtrip
import acs.pgn_workspace as pgn_workspace
from acs.gametree import PgnGame, VariationLine
from acs.pgn_roundtrip import (
    PgnRoundTripError,
    PgnRoundTripErrorCode,
    serialize_pgn_text,
)
from acs.pgn_workspace import PgnWorkspace, PgnWorkspaceError, PgnWorkspaceErrorCode


class _GuardedGames:
    """Iterable that explodes if a consumer reads beyond limit + 1."""

    def __init__(self, allowed_pulls: int) -> None:
        self.allowed_pulls = allowed_pulls
        self.pulls = 0

    def __iter__(self):
        index = 0
        while True:
            self.pulls += 1
            if self.pulls > self.allowed_pulls:
                raise AssertionError("PGN consumer read beyond the bounded sentinel")
            yield _game(index)
            index += 1


def _game(index: int) -> PgnGame:
    return PgnGame(
        tags={
            "Event": f"Bounded {index}",
            "Site": "?",
            "Date": "????.??.??",
            "Round": "?",
            "White": "?",
            "Black": "?",
            "Result": "*",
        },
        line=VariationLine(result="*"),
        source_index=index,
    )


class BoundedModelMaterializationTests(unittest.TestCase):
    def test_serializer_stops_at_limit_plus_one_for_unbounded_iterable(self) -> None:
        source = _GuardedGames(allowed_pulls=3)

        with mock.patch.object(pgn_roundtrip, "MAX_PGN_GAMES", 2):
            with self.assertRaises(PgnRoundTripError) as raised:
                serialize_pgn_text(source)

        self.assertEqual(raised.exception.code, PgnRoundTripErrorCode.GAME_COUNT_LIMIT)
        self.assertEqual(source.pulls, 3)

    def test_workspace_rejects_over_limit_before_deepcopy(self) -> None:
        source = (_game(index) for index in range(3))

        with mock.patch.object(pgn_roundtrip, "MAX_PGN_GAMES", 2):
            with mock.patch.object(
                pgn_workspace,
                "deepcopy",
                side_effect=AssertionError("workspace deep-copied before model bounds"),
            ) as copier:
                with self.assertRaises(PgnWorkspaceError) as raised:
                    PgnWorkspace(source)

        self.assertEqual(raised.exception.code, PgnWorkspaceErrorCode.INVALID_DOCUMENT)
        copier.assert_not_called()

    def test_one_shot_iterables_within_limit_remain_supported(self) -> None:
        serializer_source = (_game(index) for index in range(2))
        workspace_source = (_game(index) for index in range(2))

        with mock.patch.object(pgn_roundtrip, "MAX_PGN_GAMES", 2):
            text = serialize_pgn_text(serializer_source)
            workspace = PgnWorkspace(workspace_source)

        self.assertIn('[Event "Bounded 0"]', text)
        self.assertEqual(workspace.game_count, 2)


if __name__ == "__main__":
    unittest.main()
