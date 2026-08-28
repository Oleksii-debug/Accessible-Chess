from __future__ import annotations

"""Canonical GameTree boundary for semantic chess-book game content.

``BookDocument`` deliberately stores source-neutral semantic blocks.  This module
is the application boundary that turns a book ``Game`` or ``VariationTree``
block into the existing canonical :mod:`acs.gametree` model.  It does not parse
chess moves itself, validate legality, query ACSDB directly, or expose raw source
paths/provider details.

A referenced game is resolved through an injected port whose output is already a
canonical ``PgnGame``.  This keeps Books independent from the concrete Library /
ACSDB implementation.  A block containing both embedded PGN and ``game_id`` is
ambiguous by design; AUTO mode fails closed instead of silently preferring one
source that may have diverged from the other.
"""

from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from .bookdocument import Game, VariationTree
from .gametree import GameTreeSerializationError, PgnGame, serialize_game
from .pgn_roundtrip import PgnRoundTripError, parse_pgn_text


class BookGameContentErrorCode(str, Enum):
    INVALID_BLOCK = "invalid_block"
    AMBIGUOUS_SOURCE = "ambiguous_source"
    EMBEDDED_GAME_MISSING = "embedded_game_missing"
    REFERENCED_GAME_MISSING = "referenced_game_missing"
    LOOKUP_REQUIRED = "lookup_required"
    INVALID_LOOKUP = "invalid_lookup"
    GAME_NOT_FOUND = "game_not_found"
    INVALID_CANONICAL_GAME = "invalid_canonical_game"
    MULTI_GAME_BLOCK = "multi_game_block"
    ROOT_FEN_CONFLICT = "root_fen_conflict"


class BookGameContentError(ValueError):
    """Stable Book→GameTree boundary failure without backend internals."""

    def __init__(self, message: str, *, code: BookGameContentErrorCode) -> None:
        super().__init__(message)
        self.code = BookGameContentErrorCode(code)


class BookGameSource(str, Enum):
    AUTO = "auto"
    EMBEDDED = "embedded"
    REFERENCE = "reference"


class BookGameLookup(Protocol):
    """Library/application port for resolving a referenced canonical game."""

    def load_book_game(self, game_id: int) -> PgnGame:
        """Return one canonical GameTree game for ``game_id`` or raise LookupError."""


@dataclass(frozen=True, slots=True)
class ResolvedBookGame:
    game: PgnGame
    source: BookGameSource
    block_id: str | None
    source_anchor: str | None
    title: str | None
    game_id: int | None
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ResolvedBookVariation:
    root_fen: str
    game: PgnGame
    block_id: str | None
    source_anchor: str | None
    title: str | None
    warnings: tuple[str, ...]


def _source(value: object) -> BookGameSource:
    try:
        return BookGameSource(value)
    except (TypeError, ValueError) as exc:
        raise BookGameContentError(
            "book game source selection is invalid",
            code=BookGameContentErrorCode.INVALID_BLOCK,
        ) from exc


def _one_embedded_game(pgn: str) -> PgnGame:
    try:
        # Embedded Book PGN is an ingress surface, so use the existing bounded
        # D06 recovery boundary rather than calling the lower-level structural
        # parser directly.  This preserves recovery warnings while also applying
        # canonical SAN/NAG normalization and lexical/resource limits.
        games = parse_pgn_text(pgn, strict=False)
    except (PgnRoundTripError, RecursionError) as exc:
        raise BookGameContentError(
            "embedded book game could not be represented by the canonical GameTree",
            code=BookGameContentErrorCode.INVALID_CANONICAL_GAME,
        ) from exc
    if not games:
        raise BookGameContentError(
            "embedded book game contains no game",
            code=BookGameContentErrorCode.EMBEDDED_GAME_MISSING,
        )
    if len(games) != 1:
        raise BookGameContentError(
            "one Book Game block must resolve to exactly one canonical game",
            code=BookGameContentErrorCode.MULTI_GAME_BLOCK,
        )
    game = games[0]
    # Validate the complete mutable graph now.  The D06 ingress produces a
    # serializable tree, but this keeps later consumers from becoming the first
    # validation point if the canonical model contract changes.
    try:
        serialize_game(game)
    except GameTreeSerializationError as exc:
        raise BookGameContentError(
            "embedded book game is not a valid canonical GameTree",
            code=BookGameContentErrorCode.INVALID_CANONICAL_GAME,
        ) from exc
    return game


def _canonical_copy(game: object) -> PgnGame:
    if not isinstance(game, PgnGame):
        raise BookGameContentError(
            "book game lookup did not return a canonical GameTree game",
            code=BookGameContentErrorCode.INVALID_CANONICAL_GAME,
        )
    try:
        detached = deepcopy(game)
        serialize_game(detached)
    except (GameTreeSerializationError, TypeError, ValueError, RecursionError) as exc:
        raise BookGameContentError(
            "book game lookup returned an invalid canonical GameTree game",
            code=BookGameContentErrorCode.INVALID_CANONICAL_GAME,
        ) from exc
    return detached


def _reference_game(game_id: int, lookup: BookGameLookup | None) -> PgnGame:
    if lookup is None:
        raise BookGameContentError(
            "a referenced book game requires a Library game lookup",
            code=BookGameContentErrorCode.LOOKUP_REQUIRED,
        )
    loader = getattr(lookup, "load_book_game", None)
    if not callable(loader):
        raise BookGameContentError(
            "book game lookup does not expose the required application port",
            code=BookGameContentErrorCode.INVALID_LOOKUP,
        )
    try:
        game = loader(game_id)
    except LookupError as exc:
        raise BookGameContentError(
            "referenced book game was not found",
            code=BookGameContentErrorCode.GAME_NOT_FOUND,
        ) from exc
    except Exception as exc:
        # Keep provider/database exception text and local paths outside the Book
        # presentation boundary.  Machine logging belongs at the composition root.
        raise BookGameContentError(
            "referenced book game could not be opened",
            code=BookGameContentErrorCode.GAME_NOT_FOUND,
        ) from exc
    return _canonical_copy(game)


def resolve_book_game(
    block: Game,
    *,
    source: BookGameSource | str = BookGameSource.AUTO,
    lookup: BookGameLookup | None = None,
) -> ResolvedBookGame:
    """Resolve one semantic ``Game`` block into canonical GameTree content.

    ``AUTO`` is intentionally strict: exactly one of embedded PGN or ``game_id``
    must identify the source.  When a book intentionally carries both, the caller
    must explicitly choose EMBEDDED or REFERENCE after applying its provenance /
    freshness policy.
    """

    if not isinstance(block, Game):
        raise BookGameContentError(
            "book game resolver requires a Game block",
            code=BookGameContentErrorCode.INVALID_BLOCK,
        )
    selected = _source(source)
    has_embedded = bool(block.pgn.strip())
    has_reference = block.game_id is not None

    if selected is BookGameSource.AUTO:
        if has_embedded and has_reference:
            raise BookGameContentError(
                "book game has both embedded and referenced sources; choose explicitly",
                code=BookGameContentErrorCode.AMBIGUOUS_SOURCE,
            )
        if has_embedded:
            selected = BookGameSource.EMBEDDED
        elif has_reference:
            selected = BookGameSource.REFERENCE
        else:  # Defensive against post-construction mutation.
            raise BookGameContentError(
                "book game has no source",
                code=BookGameContentErrorCode.INVALID_BLOCK,
            )

    if selected is BookGameSource.EMBEDDED:
        if not has_embedded:
            raise BookGameContentError(
                "book game has no embedded PGN",
                code=BookGameContentErrorCode.EMBEDDED_GAME_MISSING,
            )
        game = _one_embedded_game(block.pgn)
    elif selected is BookGameSource.REFERENCE:
        if not has_reference:
            raise BookGameContentError(
                "book game has no referenced game identity",
                code=BookGameContentErrorCode.REFERENCED_GAME_MISSING,
            )
        assert block.game_id is not None
        game = _reference_game(block.game_id, lookup)
    else:  # Enum exhaustiveness / defensive future schema boundary.
        raise BookGameContentError(
            "book game source selection is unsupported",
            code=BookGameContentErrorCode.INVALID_BLOCK,
        )

    return ResolvedBookGame(
        game=game,
        source=selected,
        block_id=block.block_id,
        source_anchor=block.source_anchor,
        title=block.title,
        game_id=block.game_id,
        warnings=tuple(game.warnings),
    )


def resolve_book_variation(block: VariationTree) -> ResolvedBookVariation:
    """Resolve a semantic variation block with its explicit root position.

    Embedded variation PGN uses the existing bounded D06 recovery boundary.  This
    adapter does not synthesize moves, FEN tags, or legality.  If the source PGN
    itself carries a FEN tag, a mismatch with the Book block's explicit
    ``root_fen`` fails closed instead of choosing one silently.
    """

    if not isinstance(block, VariationTree):
        raise BookGameContentError(
            "book variation resolver requires a VariationTree block",
            code=BookGameContentErrorCode.INVALID_BLOCK,
        )
    game = _one_embedded_game(block.pgn)
    tagged_fen = game.tags.get("FEN")
    if tagged_fen is not None and tagged_fen.strip() != block.root_fen:
        raise BookGameContentError(
            "book variation root position conflicts with its PGN FEN tag",
            code=BookGameContentErrorCode.ROOT_FEN_CONFLICT,
        )
    return ResolvedBookVariation(
        root_fen=block.root_fen,
        game=game,
        block_id=block.block_id,
        source_anchor=block.source_anchor,
        title=block.title,
        warnings=tuple(game.warnings),
    )
