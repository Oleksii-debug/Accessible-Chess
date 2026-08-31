from __future__ import annotations

"""Stable, presentation-neutral identities for GameTree records.

Duplicate detection must not depend on PGN whitespace, header ordering, a UI
representation, SQLite row ids, or proprietary-format decoder details.  This
module therefore derives versioned hashes directly from neutral ``PgnGame``
DTOs.

Three deliberately different identity strengths are exposed:

* ``move_digest`` identifies the canonical move/variation structure from the
  same starting position. Comments, NAGs, result and metadata do not participate.
  This is the preservation-first key for recognising the same chess content
  across annotation or metadata revisions without silently merging those
  revisions.
* ``tree_digest`` identifies the complete chess/document content: start
  position, recursive move/variation structure, annotations and result.
* ``record_digest`` additionally identifies semantic PGN tags, normalized by
  key order.

Source/provenance is deliberately outside all three hashes. Source-record
identity belongs to the import/repository boundary and includes source format,
source-byte SHA-256 and source record index.

Every canonical payload is explicitly versioned. If its meaning ever changes,
a new version must be introduced instead of silently changing persisted
identity semantics.
"""

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import re
from typing import Any

from .gametree import Comment, CommentStyle, MoveNode, PgnGame, RESULTS, VariationLine

IDENTITY_SCHEMA_VERSION = 1
MOVE_IDENTITY_SCHEMA_VERSION = 1
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_ATTACHED_SYMBOLIC_NAG_RE = re.compile(r"(?:!!|\?\?|!\?|\?!|!|\?)$")
_MAX_IDENTITY_DEPTH = 128
_MAX_IDENTITY_NODES = 100_000


class GameIdentityErrorCode(str, Enum):
    INVALID_GAME = "invalid_game"
    INVALID_TAGS = "invalid_tags"
    INVALID_LINE = "invalid_line"
    INVALID_MOVE = "invalid_move"
    INVALID_COMMENT = "invalid_comment"
    CYCLIC_TREE = "cyclic_tree"
    TREE_LIMIT_EXCEEDED = "tree_limit_exceeded"


class GameIdentityContractError(ValueError):
    """Stable failure for malformed mutable GameTree identity input."""

    def __init__(self, message: str, *, code: GameIdentityErrorCode) -> None:
        super().__init__(message)
        self.code = GameIdentityErrorCode(code)


@dataclass(frozen=True, slots=True)
class GameIdentity:
    schema_version: int
    tree_digest: str
    record_digest: str

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != IDENTITY_SCHEMA_VERSION:
            raise GameIdentityContractError(
                "identity schema version is unsupported",
                code=GameIdentityErrorCode.INVALID_GAME,
            )
        for field_name, digest in (
            ("tree_digest", self.tree_digest),
            ("record_digest", self.record_digest),
        ):
            if not isinstance(digest, str) or _DIGEST_RE.fullmatch(digest) is None:
                raise GameIdentityContractError(
                    f"{field_name} must be a lowercase SHA-256 digest",
                    code=GameIdentityErrorCode.INVALID_GAME,
                )


@dataclass(frozen=True, slots=True)
class GameMoveIdentity:
    """Versioned identity for move/variation structure only.

    The key deliberately ignores comments, NAGs, result and PGN tags. It never
    authorizes record deletion or annotation merging; it only provides evidence
    that two records carry the same canonical move graph from the same start
    position. This keeps richer/different annotations and provenance intact.
    """

    schema_version: int
    move_digest: str

    def __post_init__(self) -> None:
        if (
            type(self.schema_version) is not int
            or self.schema_version != MOVE_IDENTITY_SCHEMA_VERSION
        ):
            raise GameIdentityContractError(
                "move identity schema version is unsupported",
                code=GameIdentityErrorCode.INVALID_GAME,
            )
        if not isinstance(self.move_digest, str) or _DIGEST_RE.fullmatch(self.move_digest) is None:
            raise GameIdentityContractError(
                "move_digest must be a lowercase SHA-256 digest",
                code=GameIdentityErrorCode.INVALID_GAME,
            )


class _TraversalState:
    def __init__(self) -> None:
        self.active: set[int] = set()
        self.nodes = 0

    def enter(self, value: object, *, depth: int) -> None:
        if depth > _MAX_IDENTITY_DEPTH:
            raise GameIdentityContractError(
                "GameTree identity depth exceeds the supported limit",
                code=GameIdentityErrorCode.TREE_LIMIT_EXCEEDED,
            )
        identity = id(value)
        if identity in self.active:
            raise GameIdentityContractError(
                "GameTree identity input contains a cycle",
                code=GameIdentityErrorCode.CYCLIC_TREE,
            )
        self.nodes += 1
        if self.nodes > _MAX_IDENTITY_NODES:
            raise GameIdentityContractError(
                "GameTree identity node count exceeds the supported limit",
                code=GameIdentityErrorCode.TREE_LIMIT_EXCEEDED,
            )
        self.active.add(identity)

    def leave(self, value: object) -> None:
        self.active.remove(id(value))

    def count_leaf(self) -> None:
        self.nodes += 1
        if self.nodes > _MAX_IDENTITY_NODES:
            raise GameIdentityContractError(
                "GameTree identity node count exceeds the supported limit",
                code=GameIdentityErrorCode.TREE_LIMIT_EXCEEDED,
            )


def _comment_payload(comment: Comment, state: _TraversalState) -> dict[str, str]:
    if not isinstance(comment, Comment):
        raise GameIdentityContractError(
            "identity comments must be Comment values",
            code=GameIdentityErrorCode.INVALID_COMMENT,
        )
    text = comment.text
    style = comment.style
    if not isinstance(text, str) or not isinstance(style, CommentStyle):
        raise GameIdentityContractError(
            "identity comment fields are invalid",
            code=GameIdentityErrorCode.INVALID_COMMENT,
        )
    state.count_leaf()
    return {"style": style.value, "text": text}


def _validated_san(move: MoveNode) -> str:
    san = move.san
    if (
        not isinstance(san, str)
        or not san.strip()
        or "\n" in san
        or "\r" in san
    ):
        raise GameIdentityContractError(
            "identity move SAN must be non-empty single-line text",
            code=GameIdentityErrorCode.INVALID_MOVE,
        )
    return san


def _line_payload(
    line: VariationLine,
    state: _TraversalState,
    *,
    depth: int,
) -> dict[str, Any]:
    if not isinstance(line, VariationLine):
        raise GameIdentityContractError(
            "identity lines must be VariationLine values",
            code=GameIdentityErrorCode.INVALID_LINE,
        )
    state.enter(line, depth=depth)
    try:
        if (
            not isinstance(line.leading_comments, list)
            or not isinstance(line.moves, list)
            or not isinstance(line.trailing_comments, list)
        ):
            raise GameIdentityContractError(
                "identity line collections must be lists",
                code=GameIdentityErrorCode.INVALID_LINE,
            )
        result = line.result
        if result is not None and (not isinstance(result, str) or result not in RESULTS):
            raise GameIdentityContractError(
                "identity line result is invalid",
                code=GameIdentityErrorCode.INVALID_LINE,
            )
        leading = tuple(line.leading_comments)
        moves = tuple(line.moves)
        trailing = tuple(line.trailing_comments)
        return {
            "leading_comments": [
                _comment_payload(comment, state) for comment in leading
            ],
            "moves": [_move_payload(move, state, depth=depth) for move in moves],
            "trailing_comments": [
                _comment_payload(comment, state) for comment in trailing
            ],
            "result": result,
        }
    finally:
        state.leave(line)


def _move_payload(
    move: MoveNode,
    state: _TraversalState,
    *,
    depth: int,
) -> dict[str, Any]:
    if not isinstance(move, MoveNode):
        raise GameIdentityContractError(
            "identity moves must be MoveNode values",
            code=GameIdentityErrorCode.INVALID_MOVE,
        )
    state.enter(move, depth=depth)
    try:
        san = _validated_san(move)
        if (
            not isinstance(move.nags, list)
            or any(not isinstance(nag, str) or not nag for nag in move.nags)
            or not isinstance(move.comments_before, list)
            or not isinstance(move.comments_after, list)
            or not isinstance(move.variations, list)
        ):
            raise GameIdentityContractError(
                "identity move collections are invalid",
                code=GameIdentityErrorCode.INVALID_MOVE,
            )
        nags = tuple(move.nags)
        before = tuple(move.comments_before)
        after = tuple(move.comments_after)
        variations = tuple(move.variations)
        for _ in nags:
            state.count_leaf()
        return {
            "san": san,
            "nags": list(nags),
            "comments_before": [
                _comment_payload(comment, state) for comment in before
            ],
            "comments_after": [
                _comment_payload(comment, state) for comment in after
            ],
            "variations": [
                _line_payload(variation, state, depth=depth + 1)
                for variation in variations
            ],
        }
    finally:
        state.leave(move)


def _move_identity_san(move: MoveNode) -> str:
    """Return SAN used only by the annotation-insensitive move identity.

    The current neutral parser preserves a symbolic NAG attached directly to SAN
    (for example ``e4?!``) inside ``MoveNode.san`` while a separated ``?!`` or
    ``$6`` lives in ``MoveNode.nags``. For duplicate classification those
    spellings represent the same chess move, so the identity view strips only a
    terminal standard symbolic NAG. The stored GameTree remains untouched and
    the full tree/record identities retain their original loss-preserving bytes.
    """

    san = _validated_san(move)
    normalized = _ATTACHED_SYMBOLIC_NAG_RE.sub("", san)
    if not normalized:
        raise GameIdentityContractError(
            "move identity SAN is empty after annotation normalization",
            code=GameIdentityErrorCode.INVALID_MOVE,
        )
    return normalized


def _move_only_line_payload(
    line: VariationLine,
    state: _TraversalState,
    *,
    depth: int,
) -> dict[str, Any]:
    if not isinstance(line, VariationLine):
        raise GameIdentityContractError(
            "identity lines must be VariationLine values",
            code=GameIdentityErrorCode.INVALID_LINE,
        )
    state.enter(line, depth=depth)
    try:
        if not isinstance(line.moves, list):
            raise GameIdentityContractError(
                "identity line moves must be a list",
                code=GameIdentityErrorCode.INVALID_LINE,
            )
        return {
            "moves": [
                _move_only_payload(move, state, depth=depth) for move in tuple(line.moves)
            ]
        }
    finally:
        state.leave(line)


def _move_only_payload(
    move: MoveNode,
    state: _TraversalState,
    *,
    depth: int,
) -> dict[str, Any]:
    if not isinstance(move, MoveNode):
        raise GameIdentityContractError(
            "identity moves must be MoveNode values",
            code=GameIdentityErrorCode.INVALID_MOVE,
        )
    state.enter(move, depth=depth)
    try:
        if not isinstance(move.variations, list):
            raise GameIdentityContractError(
                "identity move variations must be a list",
                code=GameIdentityErrorCode.INVALID_MOVE,
            )
        return {
            "san": _move_identity_san(move),
            "variations": [
                _move_only_line_payload(variation, state, depth=depth + 1)
                for variation in tuple(move.variations)
            ],
        }
    finally:
        state.leave(move)


def _snapshot_tags(game: PgnGame) -> dict[str, str]:
    if not isinstance(game.tags, dict):
        raise GameIdentityContractError(
            "identity game tags must be a dictionary",
            code=GameIdentityErrorCode.INVALID_TAGS,
        )
    tags = dict(game.tags)
    if any(
        not isinstance(key, str)
        or not key
        or not isinstance(value, str)
        for key, value in tags.items()
    ):
        raise GameIdentityContractError(
            "identity game tags must contain text keys and values",
            code=GameIdentityErrorCode.INVALID_TAGS,
        )
    return tags


def _tree_payload(
    game: PgnGame,
    tags: dict[str, str],
    state: _TraversalState,
) -> dict[str, Any]:
    start_fen = tags.get("FEN") if tags.get("SetUp") == "1" else None
    line = _line_payload(game.line, state, depth=0)
    return {
        "identity_schema": IDENTITY_SCHEMA_VERSION,
        "start_fen": start_fen,
        "line": line,
        "result": line["result"] or tags.get("Result", "*"),
    }


def _move_identity_payload(
    game: PgnGame,
    tags: dict[str, str],
    state: _TraversalState,
) -> dict[str, Any]:
    start_fen = tags.get("FEN") if tags.get("SetUp") == "1" else None
    return {
        "move_identity_schema": MOVE_IDENTITY_SCHEMA_VERSION,
        "start_fen": start_fen,
        "line": _move_only_line_payload(game.line, state, depth=0),
    }


def _record_payload(tree: dict[str, Any], tags: dict[str, str]) -> dict[str, Any]:
    return {
        "identity_schema": IDENTITY_SCHEMA_VERSION,
        "tree": tree,
        "tags": {key: tags[key] for key in sorted(tags)},
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
    """Return versioned loss-preserving identities for a neutral GameTree game."""
    if not isinstance(game, PgnGame):
        raise GameIdentityContractError(
            "identity input must be PgnGame",
            code=GameIdentityErrorCode.INVALID_GAME,
        )
    tags = _snapshot_tags(game)
    tree_payload = _tree_payload(game, tags, _TraversalState())
    return GameIdentity(
        schema_version=IDENTITY_SCHEMA_VERSION,
        tree_digest=_digest(tree_payload),
        record_digest=_digest(_record_payload(tree_payload, tags)),
    )


def move_identity_for_game(game: PgnGame) -> GameMoveIdentity:
    """Return the versioned annotation/metadata-insensitive move identity."""
    if not isinstance(game, PgnGame):
        raise GameIdentityContractError(
            "identity input must be PgnGame",
            code=GameIdentityErrorCode.INVALID_GAME,
        )
    tags = _snapshot_tags(game)
    payload = _move_identity_payload(game, tags, _TraversalState())
    return GameMoveIdentity(
        schema_version=MOVE_IDENTITY_SCHEMA_VERSION,
        move_digest=_digest(payload),
    )


def same_game_tree(left: PgnGame, right: PgnGame) -> bool:
    return identity_for_game(left).tree_digest == identity_for_game(right).tree_digest


def same_game_record(left: PgnGame, right: PgnGame) -> bool:
    return identity_for_game(left).record_digest == identity_for_game(right).record_digest


def same_game_moves(left: PgnGame, right: PgnGame) -> bool:
    """Return whether both records contain the same start position/move graph.

    This is duplicate evidence only. Callers must preserve distinct annotations,
    metadata and source provenance unless a separate explicit merge policy exists.
    """

    return move_identity_for_game(left).move_digest == move_identity_for_game(right).move_digest
