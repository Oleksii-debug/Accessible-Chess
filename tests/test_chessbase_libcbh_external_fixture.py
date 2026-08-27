from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import unittest

from acs.chessbase_decoder import (
    ChessBaseDecodeError,
    ExternalChessBaseDecoderConfig,
    decode_chessbase_external,
)
from acs.gametree import PgnGame, VariationLine, parse_games


BACKEND_COMMIT = "9641c5c3949d8fb210b17dd9aa54455645843696"


def _san(value: str) -> str:
    return value.rstrip("!?")


def _line_signature(line: VariationLine):
    return tuple(
        (
            _san(move.san),
            tuple(_line_signature(variation) for variation in move.variations),
        )
        for move in line.moves
    )


def _game_signature(game: PgnGame):
    return game.result, _line_signature(game.line)


def _first_tree_difference(
    actual: VariationLine,
    expected: VariationLine,
    *,
    path: str = "root",
) -> str | None:
    if len(actual.moves) != len(expected.moves):
        return (
            f"{path}: move count differs "
            f"(decoded={len(actual.moves)}, reference={len(expected.moves)})"
        )
    for move_index, (actual_move, expected_move) in enumerate(
        zip(actual.moves, expected.moves)
    ):
        move_path = f"{path}/move[{move_index}]"
        if _san(actual_move.san) != _san(expected_move.san):
            return (
                f"{move_path}: SAN differs "
                f"(decoded={actual_move.san!r}, reference={expected_move.san!r})"
            )
        if len(actual_move.variations) != len(expected_move.variations):
            return (
                f"{move_path} {actual_move.san!r}: variation count differs "
                f"(decoded={len(actual_move.variations)}, "
                f"reference={len(expected_move.variations)})"
            )
        for variation_index, (actual_variation, expected_variation) in enumerate(
            zip(actual_move.variations, expected_move.variations)
        ):
            difference = _first_tree_difference(
                actual_variation,
                expected_variation,
                path=f"{move_path}/variation[{variation_index}]",
            )
            if difference is not None:
                return difference
    return None


def _bounded_token_trace(bridge: Path, source: Path) -> str:
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = str(bridge.parent)
    completed = subprocess.run(
        [str(bridge), "--json-v1", str(source)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=120,
        env=env,
    )
    if completed.returncode != 0:
        return f"bridge diagnostic failed rc={completed.returncode}"
    try:
        payload = json.loads(completed.stdout.decode("utf-8", errors="strict"))
        games = payload.get("games", [])
        decoded = next(game for game in games if game.get("status") == "decoded")
        tokens = decoded.get("moves", [])
    except Exception as exc:  # diagnostic only; never hides the original failure
        return f"bridge diagnostic parse failed: {type(exc).__name__}"

    trace: list[str] = []
    depth = 0
    for index, token in enumerate(tokens[:512]):
        kind = token.get("kind")
        if kind == "move":
            trace.append(
                f"{index}:m@{depth}("
                f"{token.get('from')},{token.get('to')},{token.get('promote')})"
            )
        elif kind == "push":
            trace.append(f"{index}:push@{depth}")
            depth += 1
        elif kind == "pop":
            depth -= 1
            trace.append(f"{index}:pop@{depth}")
        else:
            trace.append(f"{index}:{kind}@{depth}")
    if len(tokens) > 512:
        trace.append(f"... total={len(tokens)}")
    return " ".join(trace)


@unittest.skipUnless(
    os.environ.get("LIBCBH_BRIDGE") and os.environ.get("LIBCBH_FIXTURE_DIR"),
    "pinned external libcbh fixture environment not configured",
)
class PinnedLibcbhFixtureIntegrationTests(unittest.TestCase):
    def test_with_variations_matches_upstream_reference_pgn_structure(self) -> None:
        bridge = Path(os.environ["LIBCBH_BRIDGE"])
        fixture = Path(os.environ["LIBCBH_FIXTURE_DIR"])
        source = fixture / "WithVariations.cbh"
        reference = fixture / "GamesWithVariations.pgn"
        self.assertTrue(source.is_file())
        self.assertTrue(reference.is_file())

        try:
            decoded = decode_chessbase_external(
                source,
                ExternalChessBaseDecoderConfig(
                    bridge,
                    expected_backend_commit=BACKEND_COMMIT,
                    timeout_seconds=120,
                    library_directory=bridge.parent,
                ),
            )
        except ChessBaseDecodeError as exc:
            self.fail(
                f"real libcbh semantic decode failed: {exc}; "
                f"first decoded token trace: {_bounded_token_trace(bridge, source)}"
            )
        reference_games = tuple(parse_games(reference.read_text(encoding="utf-8-sig")))

        self.assertFalse(
            decoded.warnings,
            f"pinned WithVariations corpus must not require skipped records: {decoded.warnings}",
        )
        self.assertEqual(decoded.total_games, len(reference_games))
        self.assertGreater(decoded.total_games, 0)

        decoded_signatures = tuple(_game_signature(game) for game in decoded.games)
        reference_signatures = tuple(_game_signature(game) for game in reference_games)
        if decoded_signatures != reference_signatures:
            first_difference = "signature mismatch without a located tree divergence"
            for game_index, (decoded_game, reference_game) in enumerate(
                zip(decoded.games, reference_games)
            ):
                difference = _first_tree_difference(decoded_game.line, reference_game.line)
                if difference is not None:
                    first_difference = f"game[{game_index}] {difference}"
                    break
            self.fail(
                f"{first_difference}; "
                f"first decoded token trace: {_bounded_token_trace(bridge, source)}"
            )

        decoded_variations = sum(
            len(move.variations)
            for game in decoded.games
            for move in game.line.moves
        )
        reference_variations = sum(
            len(move.variations)
            for game in reference_games
            for move in game.line.moves
        )
        self.assertGreater(reference_variations, 0)
        self.assertEqual(decoded_variations, reference_variations)

        # Source provenance is tied to the actual classic family that libcbh
        # opens. The bridge must not mutate any of those files.
        extensions = {item.extension for item in decoded.source.files}
        self.assertIn(".cbh", extensions)
        self.assertIn(".cbg", extensions)
        self.assertIn(".cba", extensions)


if __name__ == "__main__":
    unittest.main()
