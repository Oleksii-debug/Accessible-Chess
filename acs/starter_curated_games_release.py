from __future__ import annotations

"""Explicit curated starter-game catalogue for the V2 offline release.

The stress corpus may remain deterministic generated load data. The user-facing
starter corpus is different: every released record is a checkpoint cut from one
of sixteen explicit project-authored 20-ply instructional opening lines. No hash
or random move selection is used for starter games.
"""

from dataclasses import dataclass

from .chesscore import Board
from .starter_content import GeneratedGame, INSTRUCTIONAL_SEEDS, _movetext, _push_uci


CURATED_CATALOGUE_VERSION = 1
CURATED_LINE_PLIES = 20
CURATED_CHECKPOINT_MIN_PLIES = 6
CURATED_CHECKPOINT_MAX_PLIES = CURATED_LINE_PLIES
CURATED_GAMES_PER_LINE = CURATED_CHECKPOINT_MAX_PLIES - CURATED_CHECKPOINT_MIN_PLIES + 1
CURATED_STARTER_GAME_COUNT = len(INSTRUCTIONAL_SEEDS) * CURATED_GAMES_PER_LINE


# Explicit continuation plies 7..20 for the sixteen existing reviewed opening
# prefixes. The complete 20-ply lines are validated through the canonical Board
# before any checkpoint is published.
_CURATED_TAILS: tuple[tuple[str, ...], ...] = (
    # Italian Game
    ("d2d3", "f8c5", "c2c3", "d7d6", "e1g1", "e8g8", "f1e1", "a7a6", "c4b3", "c5a7", "b1d2", "f8e8", "d2f1", "h7h6"),
    # Ruy Lopez
    ("b5a4", "g8f6", "e1g1", "f8e7", "f1e1", "b7b5", "a4b3", "d7d6", "c2c3", "e8g8", "h2h3", "c6b8", "d2d4", "b8d7"),
    # Scotch Game
    ("f3d4", "g8f6", "d4c6", "b7c6", "f1d3", "d7d5", "e4d5", "c6d5", "e1g1", "f8e7", "f1e1", "e8g8", "c2c4", "c7c6"),
    # Vienna Game
    ("f4e5", "f6e4", "g1f3", "f8e7", "d2d4", "e8g8", "f1d3", "c7c5", "e1g1", "c5d4", "c3e4", "d5e4", "d3e4", "c8f5"),
    # Sicilian Defense
    ("f3d4", "g8f6", "b1c3", "a7a6", "c1e3", "e7e5", "d4b3", "c8e6", "f2f3", "f8e7", "d1d2", "e8g8", "e1c1", "b7b5"),
    # French Defense
    ("e4e5", "f6d7", "f2f4", "c7c5", "g1f3", "b8c6", "c1e3", "c5d4", "f3d4", "f8c5", "d1d2", "e8g8", "f1e2", "a7a6"),
    # Caro-Kann Defense
    ("c3e4", "c8f5", "e4g3", "f5g6", "h2h4", "h7h6", "g1f3", "b8d7", "h4h5", "g6h7", "f1d3", "h7d3", "d1d3", "e7e6"),
    # Scandinavian Defense
    ("d2d4", "g8f6", "g1f3", "c7c6", "f1d3", "c8g4", "c1e3", "e7e6", "h2h3", "g4h5", "d1e2", "b8d7", "e1g1", "f8e7"),
    # Queen's Gambit
    ("c1g5", "f8e7", "e2e3", "e8g8", "g1f3", "h7h6", "g5h4", "b7b6", "c4d5", "e6d5", "f1d3", "c8b7", "e1g1", "b8d7"),
    # Slav Defense
    ("b1c3", "d5c4", "a2a4", "c8f5", "e2e3", "e7e6", "f1c4", "f8b4", "e1g1", "b8d7", "d1e2", "e8g8", "e3e4", "f5g6"),
    # King's Indian Defense
    ("e2e4", "d7d6", "g1f3", "e8g8", "f1e2", "e7e5", "e1g1", "b8c6", "d4d5", "c6e7", "f3e1", "f6d7", "c1e3", "f7f5"),
    # Nimzo-Indian Defense
    ("e2e3", "e8g8", "f1d3", "d7d5", "g1f3", "c7c5", "e1g1", "b8c6", "a2a3", "b4c3", "b2c3", "d5c4", "d3c4", "d8c7"),
    # English Opening
    ("c4d5", "f6d5", "f1g2", "d5b6", "g1f3", "b8c6", "e1g1", "f8e7", "d2d3", "e8g8", "c1e3", "f7f5", "d3d4", "e5d4"),
    # Reti Opening
    ("f1g2", "f8e7", "e1g1", "e8g8", "d2d4", "c7c6", "b1c3", "b8d7", "d1d3", "b7b6", "e2e4", "c8b7", "e4e5", "f6e4"),
    # London System
    ("e2e3", "f8e7", "f1d3", "e8g8", "b1d2", "c7c5", "c2c3", "b8c6", "e1g1", "b7b6", "f3e5", "c8b7", "a2a4", "a8c8"),
    # Dutch Defense
    ("g1f3", "f8g7", "e1g1", "e8g8", "c2c4", "d7d6", "b1c3", "b8c6", "d4d5", "c6e5", "f3e5", "d6e5", "c1e3", "f5f4"),
)


@dataclass(frozen=True, slots=True)
class CuratedStarterRecord:
    line_id: str
    checkpoint_ply: int
    game: GeneratedGame


def _validated_line(seed_index: int) -> tuple[str, ...]:
    if len(_CURATED_TAILS) != len(INSTRUCTIONAL_SEEDS):
        raise RuntimeError("curated opening-line catalogue is out of sync with instructional seeds")
    seed = INSTRUCTIONAL_SEEDS[seed_index]
    line = seed.uci_moves + _CURATED_TAILS[seed_index]
    if len(line) != CURATED_LINE_PLIES:
        raise RuntimeError(f"curated line {seed_index + 1} must contain {CURATED_LINE_PLIES} plies")
    board = Board()
    for uci in line:
        _push_uci(board, uci)
    return line


def build_curated_starter_records(count: int = CURATED_STARTER_GAME_COUNT) -> tuple[CuratedStarterRecord, ...]:
    """Materialize up to 240 explicit instructional checkpoints.

    Ordering is checkpoint-major so even small test/sample subsets span multiple
    opening families rather than taking many prefixes from only one opening.
    """

    if type(count) is not int or count < 1:
        raise ValueError("count must be a positive integer")
    if count > CURATED_STARTER_GAME_COUNT:
        raise ValueError(f"count exceeds curated starter catalogue ({CURATED_STARTER_GAME_COUNT})")

    lines = tuple(_validated_line(index) for index in range(len(INSTRUCTIONAL_SEEDS)))
    records: list[CuratedStarterRecord] = []
    for checkpoint in range(CURATED_CHECKPOINT_MIN_PLIES, CURATED_CHECKPOINT_MAX_PLIES + 1):
        for seed_index, seed in enumerate(INSTRUCTIONAL_SEEDS):
            if len(records) >= count:
                return tuple(records)
            board = Board()
            san_moves: list[str] = []
            for uci in lines[seed_index][:checkpoint]:
                san_moves.append(_push_uci(board, uci))
            game_index = len(records) + 1
            records.append(
                CuratedStarterRecord(
                    line_id=f"opening-{seed_index + 1:02d}",
                    checkpoint_ply=checkpoint,
                    game=GeneratedGame(
                        index=game_index,
                        movetext=_movetext(san_moves, "*"),
                        result="*",
                        plies=checkpoint,
                        opening=seed.opening,
                        theme_uk=seed.theme_uk,
                        learning_goal_uk=seed.learning_goal_uk,
                    ),
                )
            )
    return tuple(records)


def _record_pgn(record: CuratedStarterRecord) -> str:
    game = record.game
    day = ((game.index - 1) % 28) + 1
    student = ((game.index - 1) % 24) + 1
    coach = ((game.index - 1) % 12) + 1
    tags = (
        ("Event", f"Accessible Chess — curated starter {record.line_id}"),
        ("Site", "Офлайн"),
        ("Date", f"2026.09.{day:02d}"),
        ("Round", str(game.index)),
        ("White", f"Учень {student:02d}"),
        ("Black", f"Тренер {coach:02d}"),
        ("Result", game.result),
        ("Annotator", "Accessible Chess curated instructional catalogue"),
        ("Source", "project-authored curated instructional catalogue"),
        ("Opening", game.opening),
        ("Theme", game.theme_uk),
        ("LearningGoal", game.learning_goal_uk),
        ("CuratedLine", record.line_id),
        ("CheckpointPly", str(record.checkpoint_ply)),
        ("CatalogueVersion", str(CURATED_CATALOGUE_VERSION)),
    )
    header = "\n".join(f'[{name} "{value}"]' for name, value in tags)
    comment = (
        f"{{Навчальна тема: {game.theme_uk} Мета: {game.learning_goal_uk} "
        f"Кураторський контрольний етап: {record.checkpoint_ply} півходів.}}"
    )
    return f"{header}\n\n{comment} {game.movetext}\n"


def build_curated_starter_pgn(count: int = CURATED_STARTER_GAME_COUNT) -> str:
    return "\n".join(_record_pgn(record) for record in build_curated_starter_records(count))


def curated_catalogue_manifest() -> dict[str, object]:
    return {
        "version": CURATED_CATALOGUE_VERSION,
        "line_count": len(INSTRUCTIONAL_SEEDS),
        "line_plies": CURATED_LINE_PLIES,
        "checkpoint_min_plies": CURATED_CHECKPOINT_MIN_PLIES,
        "checkpoint_max_plies": CURATED_CHECKPOINT_MAX_PLIES,
        "curated_game_count": CURATED_STARTER_GAME_COUNT,
        "opening_names": tuple(seed.opening for seed in INSTRUCTIONAL_SEEDS),
        "selection": "explicit 20-ply project-authored lines; checkpoints 6..20; no hash/random starter continuation",
    }


__all__ = [
    "CURATED_CATALOGUE_VERSION",
    "CURATED_CHECKPOINT_MAX_PLIES",
    "CURATED_CHECKPOINT_MIN_PLIES",
    "CURATED_GAMES_PER_LINE",
    "CURATED_LINE_PLIES",
    "CURATED_STARTER_GAME_COUNT",
    "CuratedStarterRecord",
    "build_curated_starter_pgn",
    "build_curated_starter_records",
    "curated_catalogue_manifest",
]
