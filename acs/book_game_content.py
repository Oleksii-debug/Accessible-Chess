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

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from .bookdocument import BookDocumentError, Game, VariationTree
from .chesscore import Board
from .gametree import (
    MAX_TREE_NODES,
    MAX_VARIATION_DEPTH,
    Comment,
    CommentStyle,
    GameTreeSerializationError,
    MoveNode,
    PgnGame,
    VariationLine,
    serialize_game,
)
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
    INVALID_ROOT_FEN = "invalid_root_fen"


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
    # Source selection is part of the same presentation-neutral scalar boundary
    # as BookDocument text.  Reject string subclasses before Enum lookup because
    # dict-backed Enum resolution can invoke attacker-controlled __hash__/__eq__
    # hooks on a str subclass.
    if type(value) is BookGameSource:
        return value
    if type(value) is not str:
        raise BookGameContentError(
            "book game source selection is invalid",
            code=BookGameContentErrorCode.INVALID_BLOCK,
        )
    try:
        return BookGameSource(value)
    except ValueError as exc:
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


def _assert_passive_provider_graph(game: PgnGame) -> None:
    """Reject provider-defined executable graph types before GameTree traversal.

    The Library lookup is outside the Books trust boundary. serialize_game remains
    the semantic PGN/GameTree authority, but it deliberately accepts subclasses
    via isinstance. Books therefore performs only a passive runtime-type/shape
    preflight before serialization so nested provider objects cannot run hooks.

    Semantic SAN/NAG/comment/result validation is intentionally left to
    serialize_game; this function only proves serializer traversal will touch
    built-in containers, exact DTOs and passive scalar values.
    """

    if type(game.tags) is not dict:
        raise TypeError("game tags must use the built-in dictionary")
    for key, value in game.tags.items():
        if type(key) is not str or type(value) is not str:
            raise TypeError("game tags must contain exact text")
    if type(game.source_index) is not int or game.source_index < 0:
        raise TypeError("game source_index must be a non-negative exact integer")
    if type(game.warnings) is not list or any(
        type(warning) is not str for warning in game.warnings
    ):
        raise TypeError("game warnings must be a built-in list of exact text")

    seen: set[int] = set()
    active_lines: set[int] = set()
    count = 0

    def claim(value: object) -> None:
        nonlocal count
        identity = id(value)
        if identity in seen:
            raise ValueError("canonical GameTree reuses a graph object")
        seen.add(identity)
        count += 1
        if count > MAX_TREE_NODES:
            raise ValueError("canonical GameTree exceeds the node safety limit")

    def check_comment(comment: object) -> None:
        if type(comment) is not Comment:
            raise TypeError("canonical comments must use exact Comment values")
        # Comment identity is not part of GameTree graph topology. The canonical
        # serializer permits one passive Comment value to be referenced from
        # multiple lists, and detachment will materialize independent copies.
        if type(comment.text) is not str:
            raise TypeError("canonical comment text must be exact text")
        if type(comment.style) not in {CommentStyle, str}:
            raise TypeError("canonical comment style must be passive scalar data")

    def check_comments(value: object) -> None:
        if type(value) is not list:
            raise TypeError("canonical comment containers must be built-in lists")
        for comment in value:
            check_comment(comment)

    def check_line(line: object, *, depth: int) -> None:
        if type(line) is not VariationLine:
            raise TypeError(
                "canonical variation lines must use exact VariationLine values"
            )
        if depth > MAX_VARIATION_DEPTH:
            raise ValueError(
                "canonical GameTree exceeds the variation depth safety limit"
            )
        line_id = id(line)
        if line_id in active_lines:
            raise ValueError("canonical GameTree contains a variation cycle")
        claim(line)
        active_lines.add(line_id)
        try:
            if type(line.moves) is not list:
                raise TypeError("canonical move containers must be built-in lists")
            check_comments(line.leading_comments)
            check_comments(line.trailing_comments)
            if line.result is not None and type(line.result) is not str:
                raise TypeError("canonical variation result must be exact text")

            for move in line.moves:
                if type(move) is not MoveNode:
                    raise TypeError("canonical moves must use exact MoveNode values")
                claim(move)
                if type(move.san) is not str:
                    raise TypeError("canonical SAN must be exact text")
                if move.move_number is not None and type(move.move_number) is not str:
                    raise TypeError("canonical move number must be exact text")
                if type(move.nags) is not list or any(
                    type(nag) is not str for nag in move.nags
                ):
                    raise TypeError(
                        "canonical NAGs must be a built-in list of exact text"
                    )
                check_comments(move.comments_before)
                check_comments(move.comments_after)
                if type(move.variations) is not list:
                    raise TypeError(
                        "canonical variation containers must be built-in lists"
                    )
                for variation in move.variations:
                    check_line(variation, depth=depth + 1)
        finally:
            active_lines.remove(line_id)

    check_line(game.line, depth=0)

def _detached_comment(comment: Comment) -> Comment:
    return Comment(text=comment.text, style=comment.style)


def _detached_move(move: MoveNode) -> MoveNode:
    return MoveNode(
        san=move.san,
        move_number=move.move_number,
        nags=list(move.nags),
        comments_before=[_detached_comment(item) for item in move.comments_before],
        comments_after=[_detached_comment(item) for item in move.comments_after],
        variations=[_detached_line(line) for line in move.variations],
    )


def _detached_line(line: VariationLine) -> VariationLine:
    return VariationLine(
        moves=[_detached_move(move) for move in line.moves],
        leading_comments=[_detached_comment(item) for item in line.leading_comments],
        trailing_comments=[_detached_comment(item) for item in line.trailing_comments],
        result=line.result,
    )


def _canonical_copy(game: object) -> PgnGame:
    # The lookup port promises the canonical concrete GameTree DTO. Reject a
    # PgnGame subclass before any provider-controlled copy hook can run.
    if type(game) is not PgnGame:
        raise BookGameContentError(
            "book game lookup did not return a canonical GameTree game",
            code=BookGameContentErrorCode.INVALID_CANONICAL_GAME,
        )
    try:
        # Prove the provider graph is passive before the canonical serializer
        # touches any nested field. Then validate PGN/GameTree semantics once
        # through the existing authority and rebuild exact detached DTO classes.
        _assert_passive_provider_graph(game)
        serialize_game(game)
        detached = PgnGame(
            tags=dict(game.tags),
            line=_detached_line(game.line),
            source_index=game.source_index,
            warnings=list(game.warnings),
        )
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
    try:
        loader = getattr(lookup, "load_book_game", None)
    except Exception:
        # Provider attribute access is part of the injected port boundary too.
        # A descriptor/__getattribute__ failure must not leak backend details.
        raise BookGameContentError(
            "book game lookup does not expose the required application port",
            code=BookGameContentErrorCode.INVALID_LOOKUP,
        ) from None
    if not callable(loader):
        raise BookGameContentError(
            "book game lookup does not expose the required application port",
            code=BookGameContentErrorCode.INVALID_LOOKUP,
        )
    try:
        game = loader(game_id)
    except LookupError:
        raise BookGameContentError(
            "referenced book game was not found",
            code=BookGameContentErrorCode.GAME_NOT_FOUND,
        ) from None
    except Exception:
        # Keep provider/database exception text and local paths outside the Book
        # presentation boundary.  Machine logging belongs at the composition root.
        raise BookGameContentError(
            "referenced book game could not be opened",
            code=BookGameContentErrorCode.GAME_NOT_FOUND,
        ) from None
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
    try:
        # Book blocks are mutable authoring objects. Rebuild one validated
        # canonical payload and use that snapshot for the entire resolution.
        # Re-reading the live block after validation would reopen a TOCTOU window:
        # authoring could change pgn/game_id or presentation metadata while a
        # lookup/parser callback is in flight.
        snapshot = block.as_dict()
    except (BookDocumentError, AttributeError) as exc:
        raise BookGameContentError(
            "book game block is invalid",
            code=BookGameContentErrorCode.INVALID_BLOCK,
        ) from exc
    pgn = snapshot.get("pgn", "")
    game_id = snapshot.get("game_id")
    if type(pgn) is not str or (
        game_id is not None
        and (type(game_id) is not int or game_id < 0)
    ):
        raise BookGameContentError(
            "book game snapshot is invalid",
            code=BookGameContentErrorCode.INVALID_BLOCK,
        )
    # BookDocument and canonical PGN ingress now share the same exact built-in
    # text boundary, so no coercion is permitted between those authorities.
    selected = _source(source)
    has_embedded = bool(pgn.strip())
    has_reference = game_id is not None

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
        game = _one_embedded_game(pgn)
    elif selected is BookGameSource.REFERENCE:
        if not has_reference:
            raise BookGameContentError(
                "book game has no referenced game identity",
                code=BookGameContentErrorCode.REFERENCED_GAME_MISSING,
            )
        assert isinstance(game_id, int) and not isinstance(game_id, bool)
        game = _reference_game(game_id, lookup)
    else:  # Enum exhaustiveness / defensive future schema boundary.
        raise BookGameContentError(
            "book game source selection is unsupported",
            code=BookGameContentErrorCode.INVALID_BLOCK,
        )

    return ResolvedBookGame(
        game=game,
        source=selected,
        block_id=snapshot.get("block_id"),
        source_anchor=snapshot.get("source_anchor"),
        title=snapshot.get("title"),
        game_id=game_id,
        warnings=tuple(game.warnings),
    )


def _canonical_root_fen(value: object) -> tuple[str, str, bool]:
    """Return preserved/canonical FEN plus whether counters were authored."""
    if type(value) is not str or not value.strip():
        raise BookGameContentError(
            "book variation root position is invalid",
            code=BookGameContentErrorCode.INVALID_ROOT_FEN,
        )
    # BookDocument's current semantic contract accepts exact built-in text only.
    # Keep that boundary after post-construction mutation too: reject subclasses
    # before calling any overridable text method.
    preserved = value.strip()
    fields = preserved.split()
    if len(fields) not in {4, 6}:
        raise BookGameContentError(
            "book variation root position is invalid",
            code=BookGameContentErrorCode.INVALID_ROOT_FEN,
        )
    try:
        canonical = Board(preserved).fen()
    except (TypeError, ValueError) as exc:
        raise BookGameContentError(
            "book variation root position is invalid",
            code=BookGameContentErrorCode.INVALID_ROOT_FEN,
        ) from exc
    return preserved, canonical, len(fields) == 4


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
    # Resolve the root first so root-FEN corruption keeps its precise stable
    # error code. Then take one canonical BookDocument snapshot and consume only
    # that payload. This closes the post-validation TOCTOU window without adding
    # a second Book/chess authority.
    try:
        live_root_fen = block.root_fen
    except AttributeError as exc:
        raise BookGameContentError(
            "book variation root position is invalid",
            code=BookGameContentErrorCode.INVALID_ROOT_FEN,
        ) from exc
    preserved_root_fen, canonical_root_fen, root_omits_counters = _canonical_root_fen(
        live_root_fen
    )
    try:
        snapshot = block.as_dict()
    except (BookDocumentError, AttributeError) as exc:
        raise BookGameContentError(
            "book variation block is invalid",
            code=BookGameContentErrorCode.INVALID_BLOCK,
        ) from exc
    snapshot_root = snapshot.get("root_fen")
    pgn = snapshot.get("pgn")
    if type(snapshot_root) is not str or type(pgn) is not str:
        raise BookGameContentError(
            "book variation snapshot is invalid",
            code=BookGameContentErrorCode.INVALID_BLOCK,
        )
    if snapshot_root != preserved_root_fen:
        raise BookGameContentError(
            "book variation changed while its canonical snapshot was captured",
            code=BookGameContentErrorCode.INVALID_BLOCK,
        )
    # Compare semantic positions canonically instead of raw strings:
    # BookDocument intentionally accepts equivalent four- and six-field FEN
    # spellings, while PGN FEN tags normally carry all six fields.
    game = _one_embedded_game(pgn)
    tagged_fen = game.tags.get("FEN")
    setup_tag = game.tags.get("SetUp")
    if tagged_fen is None:
        if setup_tag is not None:
            raise BookGameContentError(
                "book variation PGN carries SetUp without its required FEN tag",
                code=BookGameContentErrorCode.INVALID_CANONICAL_GAME,
            )
    else:
        if setup_tag != "1":
            raise BookGameContentError(
                "book variation PGN FEN requires SetUp 1",
                code=BookGameContentErrorCode.INVALID_CANONICAL_GAME,
            )
        try:
            canonical_tagged_fen = Board(tagged_fen.strip()).fen()
        except (TypeError, ValueError) as exc:
            raise BookGameContentError(
                "book variation PGN carries an invalid canonical FEN tag",
                code=BookGameContentErrorCode.INVALID_CANONICAL_GAME,
            ) from exc
        if root_omits_counters:
            # A compact four-field Book root never asserted halfmove/fullmove
            # counters. Board() necessarily synthesizes 0/1 while validating it,
            # so compare only the four authored position fields in this case.
            positions_match = (
                canonical_tagged_fen.split()[:4] == canonical_root_fen.split()[:4]
            )
        else:
            positions_match = canonical_tagged_fen == canonical_root_fen
        if not positions_match:
            raise BookGameContentError(
                "book variation root position conflicts with its PGN FEN tag",
                code=BookGameContentErrorCode.ROOT_FEN_CONFLICT,
            )
    return ResolvedBookVariation(
        root_fen=preserved_root_fen,
        game=game,
        block_id=snapshot.get("block_id"),
        source_anchor=snapshot.get("source_anchor"),
        title=snapshot.get("title"),
        warnings=tuple(game.warnings),
    )