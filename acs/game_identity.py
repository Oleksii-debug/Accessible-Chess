from __future__ import annotations

"""Stable, presentation-neutral identities for GameTree records.

Duplicate detection must not depend on PGN whitespace, header ordering, a UI
representation, SQLite row ids, or proprietary-format decoder details.  This
module therefore derives versioned hashes directly from neutral ``PgnGame``
DTOs.  Two identities are deliberately exposed:

* ``tree_digest`` identifies the chess/document content: start position,
  recursive move/variation structure, annotations and result.
* ``record_digest`` additionally identifies semantic PGN tags, normalized by
  key order.  Source/provenance belongs outside these hashes and is stored by
  the importing repository.

The canonical payload is explicitly versioned.  If its meaning ever changes,
a new version must be introduced instead of silently changing persisted
identity semantics.
"""

from dataclasses import dataclass
import hashlib
import json
from typing import Any

from .gametree import Comment, MoveNode, PgnGame, VariationLine

IDENTITY_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class GameIdentity:
    schema_version: int
    tree_digest: str
    record_digest: str


def _comment_payload(comment: Comment) -> dict[str, str]:
    return {"style": comment.style, "text": comment.text}


def _line_payload(line: VariationLine) -> dict[str, Any]:
    return {
        "leading_comments": [_comment_payload(c) for c in line.leading_comments],
        "moves": [_move_payload(move) for move in line.moves],
        "trailing_comments": [_comment_payload(c) for c in line.trailing_comments],
        "result": line.result,
    }


def _move_payload(move: MoveNode) -> dict[str, Any]:
    return {
        "san": move.san,
        "nags": list(move.nags),
        "comments_before": [_comment_payload(c) for c in move.comments_before],
        "comments_after": [_comment_payload(c) for c in move.comments_after],
        "variations": [_line_payload(v) for v in move.variations],
    }


def _tree_payload(game: PgnGame) -> dict[str, Any]:
    tags = game.tags
    start_fen = tags.get("FEN") if tags.get("SetUp") == "1" else None
    return {
        "identity_schema": IDENTITY_SCHEMA_VERSION,
        "start_fen": start_fen,
        "line": _line_payload(game.line),
        "result": game.result,
    }


def _record_payload(game: PgnGame) -> dict[str, Any]:
    return {
        "identity_schema": IDENTITY_SCHEMA_VERSION,
        "tree": _tree_payload(game),
        "tags": {key: game.tags[key] for key in sorted(game.tags)},
    }


def _digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def identity_for_game(game: PgnGame) -> GameIdentity:
    """Return versioned semantic identities for a neutral GameTree game."""
    tree_payload = _tree_payload(game)
    return GameIdentity(
        schema_version=IDENTITY_SCHEMA_VERSION,
        tree_digest=_digest(tree_payload),
        record_digest=_digest(_record_payload(game)),
    )


def same_game_tree(left: PgnGame, right: PgnGame) -> bool:
    return identity_for_game(left).tree_digest == identity_for_game(right).tree_digest


def same_game_record(left: PgnGame, right: PgnGame) -> bool:
    return identity_for_game(left).record_digest == identity_for_game(right).record_digest
