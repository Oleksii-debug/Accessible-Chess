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
from .pgn_roundtrip import (
    MAX_PGN_COMMENT_CHARS,
    MAX_PGN_LEXICAL_TOKENS,
    MAX_PGN_TAGS_PER_GAME,
    MAX_PGN_TAG_VALUE_CHARS,
    MAX_PGN_TEXT_CHARS,
    MAX_PGN_TOKEN_CHARS,
    PgnRoundTripError,
    parse_pgn_text,
)
from .game_identity import GameIdentityContractError, identity_for_game


# A bounded provider can expose parser-derived diagnostics in addition to source
# tokens. D06 emits at most token-/tag-correlated warnings plus a small number of
# whole-game consistency diagnostics, so retain explicit headroom without making
# the external Library port an unbounded diagnostic channel.
MAX_BOOK_PROVIDER_WARNINGS = (
    MAX_PGN_LEXICAL_TOKENS + MAX_PGN_TAGS_PER_GAME + 16
)
MAX_BOOK_PROVIDER_WARNING_TEXT_CHARS = MAX_PGN_TEXT_CHARS * 2


class BookGameContentErrorCode(str, Enum):
    INVALID_BLOCK = "invalid_block"
    AMBIGUOUS_SOURCE = "ambiguous_source"
    EMBEDDED_GAME_MISSING = "embedded_game_missing"
    REFERENCED_GAME_MISSING = "referenced_game_missing"
    LOOKUP_REQUIRED = "lookup_required"
    INVALID_LOOKUP = "invalid_lookup"
    GAME_NOT_FOUND = "game_not_found"
    REFERENCE_CHANGED = "reference_changed"
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
    """Reject executable or resource-unbounded provider graphs before traversal.

    The Library lookup is outside the Books trust boundary. serialize_game
    remains the semantic PGN/GameTree authority, but it deliberately accepts
    subclasses and does not own D06 source-resource limits. Books therefore
    performs only passive runtime-shape and resource preflight here: exact DTOs,
    built-in containers and exact scalar text bounded by the existing D06 PGN
    envelopes. SAN/NAG/result grammar is still decided only by serialize_game.
    """

    content_chars = 0
    warning_chars = 0
    lexical_items = 0
    serialized_header_chars = 0

    def charge_text(
        value: object,
        *,
        field: str,
        limit: int,
        diagnostic: bool = False,
    ) -> str:
        nonlocal content_chars, warning_chars
        if type(value) is not str:
            raise TypeError(f"{field} must be exact text")
        length = len(value)
        if length > limit:
            raise ValueError(f"{field} exceeds the canonical PGN field limit")
        if diagnostic:
            warning_chars += length
            if warning_chars > MAX_BOOK_PROVIDER_WARNING_TEXT_CHARS:
                raise ValueError(
                    "canonical provider warnings exceed the PGN text resource limit"
                )
        else:
            content_chars += length
            if content_chars > MAX_PGN_TEXT_CHARS:
                raise ValueError(
                    "canonical provider game exceeds the PGN text resource limit"
                )
        return value

    def claim_lexical_items(amount: int, *, field: str) -> None:
        nonlocal lexical_items
        if type(amount) is not int or amount < 0:
            raise TypeError(f"{field} count is invalid")
        lexical_items += amount
        if lexical_items > MAX_PGN_LEXICAL_TOKENS:
            raise ValueError(
                "canonical provider game exceeds the PGN lexical resource limit"
            )

    def escaped_tag_value_chars(value: str) -> int:
        # gametree._escape_tag doubles only backslashes and quotes. Count that
        # exact serialized expansion without materializing another large string.
        return len(value) + value.count("\\") + value.count('"')

    if type(game.tags) is not dict:
        raise TypeError("game tags must use the built-in dictionary")
    if len(game.tags) > MAX_PGN_TAGS_PER_GAME:
        raise ValueError("canonical provider game contains too many tag pairs")
    claim_lexical_items(len(game.tags), field="game tags")
    has_result_tag = False
    for key, value in game.tags.items():
        # D06 counts one complete tag-pair as one lexical unit and bounds the
        # full decoded source plus tag value, but it does not impose the movetext
        # token-size ceiling on a tag name. Preserve that canonical compatibility.
        key = charge_text(key, field="game tag name", limit=MAX_PGN_TEXT_CHARS)
        value = charge_text(
            value,
            field="game tag value",
            limit=MAX_PGN_TAG_VALUE_CHARS,
        )
        # `[Key "Value"]\n` = key + escaped value + six framing characters.
        serialized_header_chars += len(key) + escaped_tag_value_chars(value) + 6
        if key == "Result":
            has_result_tag = True
    if not has_result_tag:
        # serialize_game() always materializes an effective Result header. Count
        # that synthesized header as the same one lexical unit that D06 ingress
        # will see if the detached game is later round-tripped.
        claim_lexical_items(1, field="synthesized Result tag")
    if type(game.source_index) is not int or game.source_index < 0:
        raise TypeError("game source_index must be a non-negative exact integer")
    if type(game.warnings) is not list:
        raise TypeError("game warnings must be a built-in list of exact text")
    if len(game.warnings) > MAX_BOOK_PROVIDER_WARNINGS:
        raise ValueError("canonical provider game contains too many warnings")
    for warning in game.warnings:
        charge_text(
            warning,
            field="game warning",
            # Recovery warnings may quote one complete bounded source field plus
            # explanatory text, so bound them by the whole-source scalar ceiling
            # and the separate aggregate diagnostic budget above.
            limit=MAX_PGN_TEXT_CHARS,
            diagnostic=True,
        )

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

    def check_comment(comment: object) -> int:
        if type(comment) is not Comment:
            raise TypeError("canonical comments must use exact Comment values")
        # Comment identity is not part of GameTree graph topology. The canonical
        # serializer permits one passive Comment value to be referenced from
        # multiple lists, and detachment will materialize independent copies.
        text = charge_text(
            comment.text,
            field="canonical comment text",
            limit=MAX_PGN_COMMENT_CHARS,
        )
        if type(comment.style) is str:
            charge_text(
                comment.style,
                field="canonical comment style",
                limit=MAX_PGN_TOKEN_CHARS,
            )
        elif type(comment.style) is not CommentStyle:
            raise TypeError("canonical comment style must be passive scalar data")
        # Both canonical comment spellings add two characters: `{...}` or
        # `;...\n`. Semantic style validity remains serialize_game() authority.
        return len(text) + 2

    def check_comments(value: object, *, add_part) -> None:
        if type(value) is not list:
            raise TypeError("canonical comment containers must be built-in lists")
        claim_lexical_items(len(value), field="canonical comments")
        for comment in value:
            add_part(check_comment(comment))

    def check_line(line: object, *, depth: int) -> int:
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
        serialized_chars = 0
        serialized_parts = 0

        def add_part(length: int) -> None:
            nonlocal serialized_chars, serialized_parts
            if type(length) is not int or length < 0:
                raise TypeError("canonical serialized part length is invalid")
            if length == 0:
                return
            if serialized_parts:
                serialized_chars += 1  # `_serialize_line` joins parts with one space.
            serialized_chars += length
            serialized_parts += 1
            if serialized_chars > MAX_PGN_TEXT_CHARS:
                raise ValueError(
                    "canonical provider game exceeds the PGN text resource limit"
                )

        try:
            if type(line.moves) is not list:
                raise TypeError("canonical move containers must be built-in lists")
            if len(line.moves) > MAX_TREE_NODES:
                raise ValueError("canonical move container exceeds the node safety limit")
            check_comments(line.leading_comments, add_part=add_part)

            for move in line.moves:
                if type(move) is not MoveNode:
                    raise TypeError("canonical moves must use exact MoveNode values")
                claim(move)
                if move.move_number is not None:
                    move_number = charge_text(
                        move.move_number,
                        field="canonical move number",
                        limit=MAX_PGN_TOKEN_CHARS,
                    )
                    claim_lexical_items(1, field="canonical move number")
                    add_part(len(move_number))
                check_comments(move.comments_before, add_part=add_part)
                san = charge_text(
                    move.san,
                    field="canonical SAN",
                    limit=MAX_PGN_TOKEN_CHARS,
                )
                claim_lexical_items(1, field="canonical SAN")
                add_part(len(san))
                if type(move.nags) is not list:
                    raise TypeError(
                        "canonical NAGs must be a built-in list of exact text"
                    )
                claim_lexical_items(len(move.nags), field="canonical NAGs")
                for nag in move.nags:
                    nag = charge_text(
                        nag,
                        field="canonical NAG",
                        limit=MAX_PGN_TOKEN_CHARS,
                    )
                    add_part(len(nag))
                check_comments(move.comments_after, add_part=add_part)
                if type(move.variations) is not list:
                    raise TypeError(
                        "canonical variation containers must be built-in lists"
                    )
                if len(move.variations) > MAX_TREE_NODES:
                    raise ValueError(
                        "canonical variation container exceeds the node safety limit"
                    )
                # Each serialized variation contributes one opening and one
                # closing parenthesis, and D06 counts both as lexical tokens.
                claim_lexical_items(
                    len(move.variations) * 2,
                    field="canonical variation delimiters",
                )
                for variation in move.variations:
                    add_part(check_line(variation, depth=depth + 1) + 2)

            if line.result is not None:
                result = charge_text(
                    line.result,
                    field="canonical variation result",
                    limit=MAX_PGN_TOKEN_CHARS,
                )
                claim_lexical_items(1, field="canonical variation result")
                add_part(len(result))
            check_comments(line.trailing_comments, add_part=add_part)
            return serialized_chars
        finally:
            active_lines.remove(line_id)

    serialized_movetext_chars = check_line(game.line, depth=0)
    if not has_result_tag:
        # PgnGame.result uses line.result when truthy and otherwise `*` because
        # there is no provider Result tag. Exact line text has already been
        # validated above, so this is passive scalar selection, not chess logic.
        effective_result = game.line.result or "*"
        serialized_header_chars += (
            len("Result") + escaped_tag_value_chars(effective_result) + 6
        )

    # Header rows already include their trailing newlines. serialize_game adds
    # one extra blank-line newline, strips only boundary whitespace from the
    # movetext, then adds the final newline. Not subtracting a possible stripped
    # semicolon-comment newline is a safe one-character upper bound.
    serialized_total_chars = serialized_header_chars + 1 + serialized_movetext_chars + 1
    if serialized_total_chars > MAX_PGN_TEXT_CHARS:
        raise ValueError(
            "canonical provider serialization exceeds the PGN text resource limit"
        )


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
        expected_digest = snapshot.get("game_record_digest")
        if expected_digest is not None:
            try:
                actual_digest = identity_for_game(game).record_digest
            except GameIdentityContractError:
                raise BookGameContentError(
                    "referenced book game identity could not be verified",
                    code=BookGameContentErrorCode.INVALID_CANONICAL_GAME,
                ) from None
            if actual_digest != expected_digest:
                raise BookGameContentError(
                    "referenced book game no longer matches the book identity",
                    code=BookGameContentErrorCode.REFERENCE_CHANGED,
                )
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