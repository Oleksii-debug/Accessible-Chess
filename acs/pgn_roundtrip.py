from __future__ import annotations

"""Strict, bounded PGN round-trip boundary for the canonical GameTree.

The historical :mod:`acs.gametree` parser intentionally has a recovery mode so
inspectors can report damaged sources without throwing useful evidence away.
That behavior is valuable for read-only inspection, but it is not a safe edit /
write contract: duplicate tags, unterminated comments, unmatched RAV markers or
missing termination markers can require recovery and therefore cannot be called
lossless.

This module provides the D06 persistence boundary used when a PGN is expected to
be editable and round-trip safe.  It deliberately does *not* own chess legality,
Position/History, filesystem publication, or UI behavior.
"""

from dataclasses import dataclass
from enum import Enum
import re
from typing import Iterable

from .gametree import (
    Comment,
    GameTreeSerializationError,
    MAX_TREE_NODES,
    MAX_VARIATION_DEPTH,
    MoveNode,
    NAG_SYMBOLS,
    PgnGame,
    TAG_RE,
    VariationLine,
    _scan_brace_comment_span,
    parse_games,
    serialize_games,
)

# Keep the in-memory/codec ceiling aligned with the established file-import
# ceiling used by the safe PGN file adapter.  More specific lexical limits stop
# a single hostile field from monopolising that whole budget.
MAX_PGN_SOURCE_BYTES = 64 * 1024 * 1024
MAX_PGN_TEXT_CHARS = 64 * 1024 * 1024
MAX_PGN_LEXICAL_TOKENS = 500_000
MAX_PGN_TOKEN_CHARS = 4_096
MAX_PGN_COMMENT_CHARS = 1 * 1024 * 1024
MAX_PGN_TAG_VALUE_CHARS = 1 * 1024 * 1024
MAX_PGN_TAGS_PER_GAME = 4_096
MAX_PGN_GAMES = 100_000


class PgnRoundTripErrorCode(str, Enum):
    INVALID_TEXT = "invalid_text"
    INVALID_BYTES = "invalid_bytes"
    INVALID_ENCODING = "invalid_encoding"
    EMPTY_PGN = "empty_pgn"
    MALFORMED_HEADER = "malformed_header"
    MALFORMED_PGN = "malformed_pgn"
    INVALID_SAN = "invalid_san"
    INVALID_MODEL = "invalid_model"
    BYTE_SIZE_LIMIT = "byte_size_limit"
    TEXT_SIZE_LIMIT = "text_size_limit"
    TOKEN_SIZE_LIMIT = "token_size_limit"
    TOKEN_COUNT_LIMIT = "token_count_limit"
    COMMENT_SIZE_LIMIT = "comment_size_limit"
    TAG_SIZE_LIMIT = "tag_size_limit"
    TAG_COUNT_LIMIT = "tag_count_limit"
    GAME_COUNT_LIMIT = "game_count_limit"
    ROUND_TRIP_MISMATCH = "round_trip_mismatch"


class PgnRoundTripError(ValueError):
    """Stable failure for strict PGN persistence/round-trip operations."""

    def __init__(self, message: str, *, code: PgnRoundTripErrorCode) -> None:
        super().__init__(message)
        self.code = PgnRoundTripErrorCode(code)


@dataclass(frozen=True, slots=True)
class PgnRoundTripResult:
    """One canonical serialization and the reparsed equivalent GameTrees."""

    text: str
    games: tuple[PgnGame, ...]


_SAN_RE = re.compile(
    r"^(?:"
    r"O-O(?:-O)?"
    r"|--"
    r"|[a-h](?:x[a-h])?[1-8](?:=[QRBN])?"
    r"|[KQRBN](?:[a-h]|[1-8]|[a-h][1-8])?x?[a-h][1-8]"
    r")(?:\+{1,2}|#)?$"
)
_ANNOTATION_SUFFIXES = tuple(sorted(NAG_SYMBOLS, key=len, reverse=True))


def _raise_limit(message: str, code: PgnRoundTripErrorCode) -> None:
    raise PgnRoundTripError(message, code=code)


def _claim_token(counter: list[int]) -> None:
    counter[0] += 1
    if counter[0] > MAX_PGN_LEXICAL_TOKENS:
        _raise_limit(
            "PGN contains too many lexical tokens",
            PgnRoundTripErrorCode.TOKEN_COUNT_LIMIT,
        )


def _preflight_recovered_brace_comment_lengths(normalized: str) -> None:
    """Enforce the comment cap before nested-comment recovery allocates text."""

    index = 0
    length = len(normalized)
    while index < length:
        if index == 0 or normalized[index - 1] == "\n":
            line_end = normalized.find("\n", index)
            if line_end < 0:
                line_end = length
            if TAG_RE.match(normalized[index:line_end]):
                index = line_end
                continue

        character = normalized[index]
        if character == ";":
            line_end = normalized.find("\n", index + 1)
            index = length if line_end < 0 else line_end
            continue
        if character != "{":
            index += 1
            continue

        next_index, _nested, unterminated = _scan_brace_comment_span(normalized, index)
        delimiter_chars = 1 if unterminated else 2
        comment_chars = next_index - index - delimiter_chars
        if comment_chars > MAX_PGN_COMMENT_CHARS:
            _raise_limit(
                "PGN brace comment exceeds the field safety limit",
                PgnRoundTripErrorCode.COMMENT_SIZE_LIMIT,
            )
        index = next_index


def _preflight_text(text: object) -> str:
    """Bound lexical work before the recovery parser allocates token objects."""

    if type(text) is not str:
        raise PgnRoundTripError(
            "PGN text must be exact text",
            code=PgnRoundTripErrorCode.INVALID_TEXT,
        )
    if len(text) > MAX_PGN_TEXT_CHARS:
        _raise_limit(
            "PGN text exceeds the character safety limit",
            PgnRoundTripErrorCode.TEXT_SIZE_LIMIT,
        )

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    _preflight_recovered_brace_comment_lengths(normalized)
    inside_brace = False
    brace_length = 0
    token_count = [0]
    tags_in_game = 0
    seen_movetext = False

    for line in normalized.split("\n"):
        # Match the same header grammar as gametree while outside multiline
        # brace comments.  A line that looks like a header but does not satisfy
        # the grammar is not silently reinterpreted as a SAN token stream.
        if not inside_brace and line.lstrip().startswith("["):
            match = TAG_RE.match(line)
            if match is None:
                raise PgnRoundTripError(
                    "PGN contains a malformed tag-pair line",
                    code=PgnRoundTripErrorCode.MALFORMED_HEADER,
                )
            if seen_movetext:
                tags_in_game = 0
                seen_movetext = False
            tags_in_game += 1
            if tags_in_game > MAX_PGN_TAGS_PER_GAME:
                _raise_limit(
                    "PGN game contains too many tag pairs",
                    PgnRoundTripErrorCode.TAG_COUNT_LIMIT,
                )
            if len(match.group(2)) > MAX_PGN_TAG_VALUE_CHARS:
                _raise_limit(
                    "PGN tag value exceeds the field safety limit",
                    PgnRoundTripErrorCode.TAG_SIZE_LIMIT,
                )
            _claim_token(token_count)
            continue

        if line.strip() and not inside_brace:
            seen_movetext = True

        token_length = 0

        def flush_token() -> None:
            nonlocal token_length
            if token_length:
                _claim_token(token_count)
                token_length = 0

        index = 0
        while index < len(line):
            character = line[index]
            if inside_brace:
                if character == "}":
                    inside_brace = False
                    _claim_token(token_count)
                    brace_length = 0
                else:
                    brace_length += 1
                    if brace_length > MAX_PGN_COMMENT_CHARS:
                        _raise_limit(
                            "PGN brace comment exceeds the field safety limit",
                            PgnRoundTripErrorCode.COMMENT_SIZE_LIMIT,
                        )
                index += 1
                continue

            if character == "{":
                flush_token()
                inside_brace = True
                brace_length = 0
                index += 1
                continue
            if character == ";":
                flush_token()
                semicolon_length = len(line) - index - 1
                if semicolon_length > MAX_PGN_COMMENT_CHARS:
                    _raise_limit(
                        "PGN semicolon comment exceeds the field safety limit",
                        PgnRoundTripErrorCode.COMMENT_SIZE_LIMIT,
                    )
                _claim_token(token_count)
                break
            if character.isspace():
                flush_token()
                index += 1
                continue
            if character in "()":
                flush_token()
                _claim_token(token_count)
                index += 1
                continue
            if character == "[" and token_length == 0:
                raise PgnRoundTripError(
                    "PGN tag marker appears inside movetext",
                    code=PgnRoundTripErrorCode.MALFORMED_HEADER,
                )

            token_length += 1
            if token_length > MAX_PGN_TOKEN_CHARS:
                _raise_limit(
                    "PGN token exceeds the lexical safety limit",
                    PgnRoundTripErrorCode.TOKEN_SIZE_LIMIT,
                )
            index += 1

        flush_token()
        if inside_brace:
            # Preserve a bounded accounting unit for the newline that belongs
            # to a multiline brace comment.
            brace_length += 1
            if brace_length > MAX_PGN_COMMENT_CHARS:
                _raise_limit(
                    "PGN brace comment exceeds the field safety limit",
                    PgnRoundTripErrorCode.COMMENT_SIZE_LIMIT,
                )

    return normalized


def decode_pgn_bytes(data: object) -> str:
    """Decode UTF-8/UTF-8-BOM PGN strictly; invalid bytes never get replaced."""

    if type(data) is not bytes:
        raise PgnRoundTripError(
            "PGN byte input must be exact bytes",
            code=PgnRoundTripErrorCode.INVALID_BYTES,
        )
    if len(data) > MAX_PGN_SOURCE_BYTES:
        _raise_limit(
            "PGN byte input exceeds the safety limit",
            PgnRoundTripErrorCode.BYTE_SIZE_LIMIT,
        )
    try:
        text = data.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise PgnRoundTripError(
            "PGN is not valid UTF-8",
            code=PgnRoundTripErrorCode.INVALID_ENCODING,
        ) from exc
    return _preflight_text(text)


def _split_attached_annotation(node: MoveNode) -> None:
    san = node.san
    for suffix in _ANNOTATION_SUFFIXES:
        if san.endswith(suffix) and len(san) > len(suffix):
            node.san = san[: -len(suffix)]
            node.nags.insert(0, suffix)
            return


def _validate_san(san: object) -> None:
    if type(san) is not str or not _SAN_RE.fullmatch(san):
        raise PgnRoundTripError(
            "PGN contains unsupported or malformed SAN text",
            code=PgnRoundTripErrorCode.INVALID_SAN,
        )


def _validate_parsed_comment_size(comment: object) -> None:
    if not isinstance(comment, Comment) or type(comment.text) is not str:
        raise PgnRoundTripError(
            "PGN contains an invalid comment model",
            code=PgnRoundTripErrorCode.INVALID_MODEL,
        )
    if len(comment.text) > MAX_PGN_COMMENT_CHARS:
        _raise_limit(
            "PGN comment exceeds the field safety limit",
            PgnRoundTripErrorCode.COMMENT_SIZE_LIMIT,
        )


def _normalize_and_validate_line(line: VariationLine, *, depth: int = 0) -> None:
    if depth > MAX_VARIATION_DEPTH:
        _raise_limit(
            "PGN variation nesting exceeds the safety limit",
            PgnRoundTripErrorCode.TOKEN_COUNT_LIMIT,
        )
    for comment in line.leading_comments:
        _validate_parsed_comment_size(comment)
    for node in line.moves:
        _split_attached_annotation(node)
        _validate_san(node.san)
        for comment in node.comments_before:
            _validate_parsed_comment_size(comment)
        for comment in node.comments_after:
            _validate_parsed_comment_size(comment)
        for variation in node.variations:
            _normalize_and_validate_line(variation, depth=depth + 1)
    for comment in line.trailing_comments:
        _validate_parsed_comment_size(comment)


def parse_pgn_text(text: object, *, strict: bool = True) -> tuple[PgnGame, ...]:
    """Parse bounded PGN into canonical GameTrees.

    ``strict=True`` is the edit/write contract: any recovery warning means the
    source is not lossless-round-trip safe and the whole operation fails closed.
    ``strict=False`` keeps the historical recovery semantics for read-only
    inspection while retaining D06 resource bounds and SAN normalization.
    """

    normalized = _preflight_text(text)
    games = tuple(parse_games(normalized))
    if len(games) > MAX_PGN_GAMES:
        _raise_limit(
            "PGN contains too many games",
            PgnRoundTripErrorCode.GAME_COUNT_LIMIT,
        )
    if strict and not games:
        raise PgnRoundTripError(
            "PGN contains no game",
            code=PgnRoundTripErrorCode.EMPTY_PGN,
        )

    for game in games:
        _normalize_and_validate_line(game.line)
        if strict and game.warnings:
            raise PgnRoundTripError(
                "PGN requires recovery and is not strict round-trip safe",
                code=PgnRoundTripErrorCode.MALFORMED_PGN,
            )
    return games


def parse_pgn_bytes(data: object, *, strict: bool = True) -> tuple[PgnGame, ...]:
    return parse_pgn_text(decode_pgn_bytes(data), strict=strict)


def _claim_model_chars(budget: list[int], amount: int) -> None:
    budget[0] += amount
    if budget[0] > MAX_PGN_TEXT_CHARS:
        _raise_limit(
            "PGN model exceeds the serialization safety limit",
            PgnRoundTripErrorCode.TEXT_SIZE_LIMIT,
        )


def _measure_comment(comment: object, budget: list[int]) -> None:
    if not isinstance(comment, Comment) or type(comment.text) is not str:
        raise PgnRoundTripError(
            "PGN model contains an invalid comment",
            code=PgnRoundTripErrorCode.INVALID_MODEL,
        )
    if len(comment.text) > MAX_PGN_COMMENT_CHARS:
        _raise_limit(
            "PGN comment exceeds the field safety limit",
            PgnRoundTripErrorCode.COMMENT_SIZE_LIMIT,
        )
    _claim_model_chars(budget, len(comment.text) + 16)


def _measure_line(
    line: object,
    budget: list[int],
    seen: set[int],
    active: set[int],
    node_count: list[int],
    *,
    depth: int,
) -> None:
    if not isinstance(line, VariationLine) or type(line.moves) is not list:
        raise PgnRoundTripError(
            "PGN model contains an invalid variation line",
            code=PgnRoundTripErrorCode.INVALID_MODEL,
        )
    if depth > MAX_VARIATION_DEPTH:
        _raise_limit(
            "PGN variation nesting exceeds the safety limit",
            PgnRoundTripErrorCode.TOKEN_COUNT_LIMIT,
        )
    identity = id(line)
    if identity in active or identity in seen:
        raise PgnRoundTripError(
            "PGN model contains a cyclic or reused variation object",
            code=PgnRoundTripErrorCode.INVALID_MODEL,
        )
    seen.add(identity)
    active.add(identity)
    node_count[0] += 1
    if node_count[0] > MAX_TREE_NODES:
        _raise_limit(
            "PGN model exceeds the node safety limit",
            PgnRoundTripErrorCode.TOKEN_COUNT_LIMIT,
        )
    _claim_model_chars(budget, 32)

    if type(line.leading_comments) is not list or type(line.trailing_comments) is not list:
        raise PgnRoundTripError(
            "PGN model comment collections must be lists",
            code=PgnRoundTripErrorCode.INVALID_MODEL,
        )
    if line.trailing_comments and line.result is None:
        raise PgnRoundTripError(
            "PGN trailing comments require an explicit line result for lossless serialization",
            code=PgnRoundTripErrorCode.INVALID_MODEL,
        )
    for comment in line.leading_comments:
        _measure_comment(comment, budget)
    for node in line.moves:
        if not isinstance(node, MoveNode):
            raise PgnRoundTripError(
                "PGN variation contains an invalid move node",
                code=PgnRoundTripErrorCode.INVALID_MODEL,
            )
        node_identity = id(node)
        if node_identity in seen:
            raise PgnRoundTripError(
                "PGN model reuses one move node",
                code=PgnRoundTripErrorCode.INVALID_MODEL,
            )
        seen.add(node_identity)
        node_count[0] += 1
        if node_count[0] > MAX_TREE_NODES:
            _raise_limit(
                "PGN model exceeds the node safety limit",
                PgnRoundTripErrorCode.TOKEN_COUNT_LIMIT,
            )
        _validate_san(node.san)
        _claim_model_chars(budget, len(node.san) + 32)
        if node.move_number is not None:
            if type(node.move_number) is not str or len(node.move_number) > MAX_PGN_TOKEN_CHARS:
                raise PgnRoundTripError(
                    "PGN model contains an invalid move number",
                    code=PgnRoundTripErrorCode.INVALID_MODEL,
                )
            _claim_model_chars(budget, len(node.move_number) + 4)
        if type(node.nags) is not list:
            raise PgnRoundTripError(
                "PGN move NAG collection must be a list",
                code=PgnRoundTripErrorCode.INVALID_MODEL,
            )
        for nag in node.nags:
            if type(nag) is not str or len(nag) > MAX_PGN_TOKEN_CHARS:
                raise PgnRoundTripError(
                    "PGN model contains an invalid NAG",
                    code=PgnRoundTripErrorCode.INVALID_MODEL,
                )
            _claim_model_chars(budget, len(nag) + 4)
        if type(node.comments_before) is not list or type(node.comments_after) is not list:
            raise PgnRoundTripError(
                "PGN move comment collections must be lists",
                code=PgnRoundTripErrorCode.INVALID_MODEL,
            )
        for comment in node.comments_before:
            _measure_comment(comment, budget)
        for comment in node.comments_after:
            _measure_comment(comment, budget)
        if type(node.variations) is not list:
            raise PgnRoundTripError(
                "PGN move variations must be a list",
                code=PgnRoundTripErrorCode.INVALID_MODEL,
            )
        for variation in node.variations:
            _claim_model_chars(budget, 4)
            _measure_line(
                variation,
                budget,
                seen,
                active,
                node_count,
                depth=depth + 1,
            )
    for comment in line.trailing_comments:
        _measure_comment(comment, budget)
    if line.result is not None:
        if type(line.result) is not str or len(line.result) > MAX_PGN_TOKEN_CHARS:
            raise PgnRoundTripError(
                "PGN model contains an invalid result",
                code=PgnRoundTripErrorCode.INVALID_MODEL,
            )
        _claim_model_chars(budget, len(line.result) + 4)
    active.remove(identity)


def _measure_games(games: tuple[PgnGame, ...]) -> None:
    if len(games) > MAX_PGN_GAMES:
        _raise_limit(
            "PGN contains too many games",
            PgnRoundTripErrorCode.GAME_COUNT_LIMIT,
        )
    budget = [0]
    seen: set[int] = set()
    active: set[int] = set()
    node_count = [0]
    for game in games:
        if not isinstance(game, PgnGame) or type(game.tags) is not dict:
            raise PgnRoundTripError(
                "PGN serialization requires PgnGame values",
                code=PgnRoundTripErrorCode.INVALID_MODEL,
            )
        if len(game.tags) > MAX_PGN_TAGS_PER_GAME:
            _raise_limit(
                "PGN game contains too many tag pairs",
                PgnRoundTripErrorCode.TAG_COUNT_LIMIT,
            )
        _claim_model_chars(budget, 64)
        for key, value in game.tags.items():
            if type(key) is not str or type(value) is not str:
                raise PgnRoundTripError(
                    "PGN tags must contain exact text keys and values",
                    code=PgnRoundTripErrorCode.INVALID_MODEL,
                )
            if len(value) > MAX_PGN_TAG_VALUE_CHARS:
                _raise_limit(
                    "PGN tag value exceeds the field safety limit",
                    PgnRoundTripErrorCode.TAG_SIZE_LIMIT,
                )
            _claim_model_chars(budget, len(key) + len(value) + 16)
        _measure_line(game.line, budget, seen, active, node_count, depth=0)


def serialize_pgn_text(games: Iterable[PgnGame]) -> str:
    """Serialize only a bounded model that can be reparsed by the strict codec."""

    try:
        snapshot = tuple(games)
    except TypeError as exc:
        raise PgnRoundTripError(
            "PGN games must be an iterable of PgnGame values",
            code=PgnRoundTripErrorCode.INVALID_MODEL,
        ) from exc
    _measure_games(snapshot)
    try:
        text = serialize_games(snapshot)
    except GameTreeSerializationError as exc:
        raise PgnRoundTripError(
            "PGN model is not strictly serializable",
            code=PgnRoundTripErrorCode.INVALID_MODEL,
        ) from exc
    if len(text) > MAX_PGN_TEXT_CHARS:
        _raise_limit(
            "PGN serialization exceeds the character safety limit",
            PgnRoundTripErrorCode.TEXT_SIZE_LIMIT,
        )
    return text


def serialize_pgn_bytes(games: Iterable[PgnGame]) -> bytes:
    text = serialize_pgn_text(games)
    data = text.encode("utf-8", errors="strict")
    if len(data) > MAX_PGN_SOURCE_BYTES:
        _raise_limit(
            "PGN serialization exceeds the byte safety limit",
            PgnRoundTripErrorCode.BYTE_SIZE_LIMIT,
        )
    return data


def canonical_round_trip_text(text: object) -> PgnRoundTripResult:
    """Strict parse -> canonical write -> strict reparse -> equivalence proof."""

    games = parse_pgn_text(text, strict=True)
    serialized = serialize_pgn_text(games)
    reparsed = parse_pgn_text(serialized, strict=True)
    if reparsed != games:
        raise PgnRoundTripError(
            "PGN semantic structure changed during round-trip",
            code=PgnRoundTripErrorCode.ROUND_TRIP_MISMATCH,
        )
    return PgnRoundTripResult(text=serialized, games=reparsed)


def canonical_round_trip_bytes(data: object) -> tuple[bytes, tuple[PgnGame, ...]]:
    result = canonical_round_trip_text(decode_pgn_bytes(data))
    encoded = result.text.encode("utf-8", errors="strict")
    if len(encoded) > MAX_PGN_SOURCE_BYTES:
        _raise_limit(
            "PGN serialization exceeds the byte safety limit",
            PgnRoundTripErrorCode.BYTE_SIZE_LIMIT,
        )
    return encoded, result.games
