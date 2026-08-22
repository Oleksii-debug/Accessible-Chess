from __future__ import annotations

"""Loss-aware structural PGN model for the presentation-neutral data core.

This module intentionally separates *structure* from chess legality. It keeps
comments, NAGs and nested RAV branches instead of flattening them. A later
position-linking pass may validate every SAN token against chesscore.Board
without making import destructive when a historical source is damaged.

This is a reusable core boundary only. Importing it does not activate a
post-Stage-1 UI, workflow, or release path.
"""

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Iterable

RESULTS = {"1-0", "0-1", "1/2-1/2", "*"}
TAG_RE = re.compile(r'^\s*\[([A-Za-z0-9_]+)\s+"((?:\\.|[^"\\])*)"\]\s*$')
MOVE_NUMBER_RE = re.compile(r"^(\d+)\.(\.\.)?$")
TAG_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")
NAG_RE = re.compile(r"^\$\d+$")
MOVE_NUMBER_TOKEN_RE = re.compile(r"^\d+\.{1,3}$")
NAG_SYMBOLS = frozenset({"!", "?", "!!", "??", "!?", "?!"})

# Defensive structural bounds. They are intentionally high enough for real
# books/databases but low enough to prevent recursive hostile graphs or PGN RAV
# nesting from exhausting the Python stack or unbounded traversal resources.
MAX_VARIATION_DEPTH = 128
MAX_TREE_NODES = 100_000


class GameTreeErrorCode(str, Enum):
    INVALID_COMMENT_TEXT = "invalid_comment_text"
    UNSUPPORTED_COMMENT_STYLE = "unsupported_comment_style"
    UNREPRESENTABLE_COMMENT = "unrepresentable_comment"
    INVALID_GAME = "invalid_game"
    INVALID_CONTAINER = "invalid_container"
    INVALID_TAG = "invalid_tag"
    INVALID_LINE = "invalid_line"
    INVALID_MOVE = "invalid_move"
    INVALID_NAG = "invalid_nag"
    GRAPH_CYCLE = "graph_cycle"
    GRAPH_REUSE = "graph_reuse"
    GRAPH_DEPTH_LIMIT = "graph_depth_limit"
    GRAPH_NODE_LIMIT = "graph_node_limit"


class GameTreeContractError(ValueError):
    """Stable validation failure for presentation-neutral GameTree data."""

    def __init__(self, message: str, *, code: GameTreeErrorCode) -> None:
        super().__init__(message)
        self.code = GameTreeErrorCode(code)


class GameTreeSerializationError(GameTreeContractError):
    """Raised instead of silently changing data that PGN cannot represent."""


class CommentStyle(str, Enum):
    BRACE = "brace"
    SEMICOLON = "semicolon"


@dataclass(slots=True)
class Comment:
    text: str
    style: CommentStyle = CommentStyle.BRACE

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise GameTreeContractError(
                "comment text must be a string",
                code=GameTreeErrorCode.INVALID_COMMENT_TEXT,
            )
        try:
            self.style = CommentStyle(self.style)
        except (TypeError, ValueError) as exc:
            raise GameTreeContractError(
                f"unsupported comment style: {self.style!r}",
                code=GameTreeErrorCode.UNSUPPORTED_COMMENT_STYLE,
            ) from exc


@dataclass(slots=True)
class MoveNode:
    san: str
    move_number: str | None = None
    nags: list[str] = field(default_factory=list)
    comments_before: list[Comment] = field(default_factory=list)
    comments_after: list[Comment] = field(default_factory=list)
    variations: list["VariationLine"] = field(default_factory=list)


@dataclass(slots=True)
class VariationLine:
    moves: list[MoveNode] = field(default_factory=list)
    leading_comments: list[Comment] = field(default_factory=list)
    trailing_comments: list[Comment] = field(default_factory=list)
    result: str | None = None


@dataclass(slots=True)
class PgnGame:
    tags: dict[str, str] = field(default_factory=dict)
    line: VariationLine = field(default_factory=VariationLine)
    source_index: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def result(self) -> str:
        return self.line.result or self.tags.get("Result", "*")


@dataclass(slots=True)
class _Token:
    kind: str
    value: str


def _unescape_tag(value: str) -> str:
    return value.replace(r'\"', '"').replace(r"\\", "\\")


def _escape_tag(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', r'\"')


def tokenize_movetext(text: str) -> list[_Token]:
    out: list[_Token] = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
            continue
        if c == "{":
            j = i + 1
            while j < n and text[j] != "}":
                j += 1
            if j >= n:
                out.append(_Token("COMMENT_BRACE", text[i + 1 :]))
                out.append(_Token("WARNING", "unterminated brace comment"))
                break
            out.append(_Token("COMMENT_BRACE", text[i + 1 : j]))
            i = j + 1
            continue
        if c == ";":
            j = text.find("\n", i + 1)
            if j < 0:
                j = n
            out.append(_Token("COMMENT_SEMI", text[i + 1 : j].rstrip("\r")))
            i = j
            continue
        if c == "(":
            out.append(_Token("LPAREN", c)); i += 1; continue
        if c == ")":
            out.append(_Token("RPAREN", c)); i += 1; continue
        if c == "$":
            j = i + 1
            while j < n and text[j].isdigit():
                j += 1
            if j > i + 1:
                out.append(_Token("NAG", text[i:j])); i = j; continue
        j = i
        while j < n and not text[j].isspace() and text[j] not in "{};()":
            j += 1
        value = text[i:j]
        if value in RESULTS:
            kind = "RESULT"
        elif MOVE_NUMBER_RE.fullmatch(value) or re.fullmatch(r"\d+\.{1,3}", value):
            kind = "MOVE_NUMBER"
        elif value in NAG_SYMBOLS:
            kind = "NAG_SYMBOL"
        else:
            m = re.match(r"^(\d+\.{1,3})(.+)$", value)
            if m:
                out.append(_Token("MOVE_NUMBER", m.group(1)))
                value = m.group(2)
            kind = "SAN"
        if value:
            out.append(_Token(kind, value))
        i = j
    return out


def _claim_parse_node(budget: list[int]) -> None:
    budget[0] += 1
    if budget[0] > MAX_TREE_NODES:
        raise GameTreeContractError(
            "PGN structure exceeds the node safety limit",
            code=GameTreeErrorCode.GRAPH_NODE_LIMIT,
        )


def _parse_line(
    tokens: list[_Token],
    pos: int = 0,
    *,
    nested: bool = False,
    depth: int = 0,
    budget: list[int] | None = None,
) -> tuple[VariationLine, int, list[str]]:
    if depth > MAX_VARIATION_DEPTH:
        raise GameTreeContractError(
            "PGN variation nesting exceeds the depth safety limit",
            code=GameTreeErrorCode.GRAPH_DEPTH_LIMIT,
        )
    if budget is None:
        budget = [1]  # root VariationLine
    line = VariationLine()
    warnings: list[str] = []
    pending_number: str | None = None
    pending_comments: list[Comment] = []
    last: MoveNode | None = None

    while pos < len(tokens):
        tok = tokens[pos]
        if tok.kind == "WARNING":
            warnings.append(tok.value); pos += 1; continue
        if tok.kind == "RPAREN":
            if not nested:
                warnings.append("unmatched closing parenthesis")
                pos += 1
                continue
            break
        if tok.kind == "LPAREN":
            if depth >= MAX_VARIATION_DEPTH:
                raise GameTreeContractError(
                    "PGN variation nesting exceeds the depth safety limit",
                    code=GameTreeErrorCode.GRAPH_DEPTH_LIMIT,
                )
            _claim_parse_node(budget)  # child VariationLine
            pos += 1
            child, pos, child_warnings = _parse_line(
                tokens,
                pos,
                nested=True,
                depth=depth + 1,
                budget=budget,
            )
            warnings.extend(child_warnings)
            if pos < len(tokens) and tokens[pos].kind == "RPAREN":
                pos += 1
            else:
                warnings.append("unterminated variation")
            if last is not None:
                last.variations.append(child)
            else:
                warnings.append("variation has no preceding move")
                line.trailing_comments.extend(child.leading_comments)
            continue
        if tok.kind in {"COMMENT_BRACE", "COMMENT_SEMI"}:
            comment = Comment(tok.value, "brace" if tok.kind == "COMMENT_BRACE" else "semicolon")
            if last is None and pending_number is None:
                line.leading_comments.append(comment)
            elif pending_number is not None:
                pending_comments.append(comment)
            else:
                last.comments_after.append(comment)
            pos += 1
            continue
        if tok.kind == "MOVE_NUMBER":
            pending_number = tok.value
            pos += 1
            continue
        if tok.kind in {"NAG", "NAG_SYMBOL"}:
            if last is None:
                warnings.append(f"orphan annotation {tok.value}")
            else:
                last.nags.append(tok.value)
            pos += 1
            continue
        if tok.kind == "RESULT":
            line.result = tok.value
            pos += 1
            while pos < len(tokens):
                trailing = tokens[pos]
                if trailing.kind == "WARNING":
                    warnings.append(trailing.value)
                    pos += 1
                    continue
                if trailing.kind not in {"COMMENT_BRACE", "COMMENT_SEMI"}:
                    break
                line.trailing_comments.append(
                    Comment(
                        trailing.value,
                        "brace" if trailing.kind == "COMMENT_BRACE" else "semicolon",
                    )
                )
                pos += 1
            break
        if tok.kind == "SAN":
            _claim_parse_node(budget)  # MoveNode
            node = MoveNode(tok.value, move_number=pending_number, comments_before=pending_comments)
            pending_number = None
            pending_comments = []
            line.moves.append(node)
            last = node
            pos += 1
            continue
        warnings.append(f"unknown token {tok.kind}:{tok.value}")
        pos += 1

    if pending_comments:
        if line.moves:
            line.trailing_comments.extend(pending_comments)
        else:
            line.leading_comments.extend(pending_comments)
    return line, pos, warnings


def _brace_comment_state_after_line(line: str, inside_comment: bool) -> bool:
    """Track PGN brace comments so tag-looking comment lines stay movetext."""

    for character in line:
        if inside_comment:
            if character == "}":
                inside_comment = False
            continue
        if character == ";":
            break
        if character == "{":
            inside_comment = True
    return inside_comment


def _split_games(text: str) -> list[tuple[dict[str, str], str, list[str]]]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    games: list[tuple[dict[str, str], str, list[str]]] = []
    tags: dict[str, str] = {}
    moves: list[str] = []
    split_warnings: list[str] = []
    seen_movetext = False
    inside_brace_comment = False

    def flush() -> None:
        nonlocal tags, moves, split_warnings, seen_movetext, inside_brace_comment
        if tags or any(x.strip() for x in moves):
            games.append((tags, "\n".join(moves).strip(), split_warnings))
        tags = {}
        moves = []
        split_warnings = []
        seen_movetext = False
        inside_brace_comment = False

    for line in lines:
        m = None if inside_brace_comment else TAG_RE.match(line)
        if m:
            if seen_movetext:
                flush()
            key = m.group(1)
            if key in tags:
                split_warnings.append(f"duplicate tag {key}; last value preserved")
            tags[key] = _unescape_tag(m.group(2))
            continue
        if line.strip():
            seen_movetext = True
        if seen_movetext or moves:
            moves.append(line)
        inside_brace_comment = _brace_comment_state_after_line(
            line,
            inside_brace_comment,
        )
    flush()
    return games


def parse_games(text: str) -> list[PgnGame]:
    games: list[PgnGame] = []
    for index, (tags, movetext, split_warnings) in enumerate(_split_games(text)):
        tokens = tokenize_movetext(movetext)
        line, pos, warnings = _parse_line(tokens)
        warnings[:0] = split_warnings
        if pos < len(tokens):
            warnings.append(f"{len(tokens) - pos} unconsumed token(s)")
        header_result = tags.get("Result")
        valid_header_result = header_result if header_result in RESULTS else None
        if header_result is not None and valid_header_result is None:
            warnings.append(f"invalid header Result {header_result}")
        if line.result and valid_header_result and line.result != valid_header_result:
            warnings.append(f"header Result {header_result} differs from movetext {line.result}")
        if not line.result:
            line.result = valid_header_result or "*"
        tags = dict(tags)
        tags.setdefault("Result", line.result)
        games.append(PgnGame(tags=tags, line=line, source_index=index, warnings=warnings))
    return games


def _serialize_comment(c: Comment) -> str:
    if not isinstance(c, Comment):
        raise GameTreeSerializationError(
            "comment collections must contain Comment values",
            code=GameTreeErrorCode.INVALID_CONTAINER,
        )
    if not isinstance(c.text, str):
        raise GameTreeSerializationError(
            "comment text must be a string",
            code=GameTreeErrorCode.INVALID_COMMENT_TEXT,
        )
    try:
        style = CommentStyle(c.style)
    except (TypeError, ValueError) as exc:
        raise GameTreeSerializationError(
            f"unsupported comment style: {c.style!r}",
            code=GameTreeErrorCode.UNSUPPORTED_COMMENT_STYLE,
        ) from exc

    if style is CommentStyle.BRACE:
        if "}" in c.text:
            raise GameTreeSerializationError(
                "brace comment contains an unrepresentable closing brace",
                code=GameTreeErrorCode.UNREPRESENTABLE_COMMENT,
            )
        return "{" + c.text + "}"

    if "\r" in c.text or "\n" in c.text:
        raise GameTreeSerializationError(
            "semicolon comment contains an unrepresentable line break",
            code=GameTreeErrorCode.UNREPRESENTABLE_COMMENT,
        )
    return ";" + c.text + "\n"


def _require_comment_list(value: object, *, field_name: str) -> list[Comment]:
    if type(value) is not list:
        raise GameTreeSerializationError(
            f"{field_name} must be a list",
            code=GameTreeErrorCode.INVALID_CONTAINER,
        )
    for comment in value:
        _serialize_comment(comment)
    return value


def _validate_san(san: object) -> None:
    if not isinstance(san, str) or not san or san != san.strip():
        raise GameTreeSerializationError(
            "move SAN must be non-empty canonical text",
            code=GameTreeErrorCode.INVALID_MOVE,
        )
    if (
        any(character.isspace() for character in san)
        or any(character in "{};()" for character in san)
        or san in RESULTS
        or MOVE_NUMBER_TOKEN_RE.fullmatch(san)
        or NAG_RE.fullmatch(san)
        or san in NAG_SYMBOLS
    ):
        raise GameTreeSerializationError(
            "move SAN would be reinterpreted as PGN structure",
            code=GameTreeErrorCode.INVALID_MOVE,
        )


def _validate_nags(nags: object) -> None:
    if type(nags) is not list:
        raise GameTreeSerializationError(
            "move nags must be a list",
            code=GameTreeErrorCode.INVALID_CONTAINER,
        )
    for nag in nags:
        if not isinstance(nag, str) or not (NAG_RE.fullmatch(nag) or nag in NAG_SYMBOLS):
            raise GameTreeSerializationError(
                "move NAG is not representable PGN annotation data",
                code=GameTreeErrorCode.INVALID_NAG,
            )


def _claim_export_node(state: dict[str, object]) -> None:
    count = int(state["count"]) + 1
    state["count"] = count
    if count > MAX_TREE_NODES:
        raise GameTreeSerializationError(
            "GameTree exceeds the node safety limit",
            code=GameTreeErrorCode.GRAPH_NODE_LIMIT,
        )


def _validate_line_for_serialization(
    line: object,
    *,
    depth: int,
    state: dict[str, object],
) -> None:
    if not isinstance(line, VariationLine):
        raise GameTreeSerializationError(
            "game line must be a VariationLine",
            code=GameTreeErrorCode.INVALID_LINE,
        )
    if depth > MAX_VARIATION_DEPTH:
        raise GameTreeSerializationError(
            "GameTree variation nesting exceeds the depth safety limit",
            code=GameTreeErrorCode.GRAPH_DEPTH_LIMIT,
        )

    seen = state["seen"]
    active = state["active"]
    assert isinstance(seen, set) and isinstance(active, set)
    identity = id(line)
    if identity in active:
        raise GameTreeSerializationError(
            "GameTree contains a cyclic variation reference",
            code=GameTreeErrorCode.GRAPH_CYCLE,
        )
    if identity in seen:
        raise GameTreeSerializationError(
            "GameTree reuses one VariationLine in multiple locations",
            code=GameTreeErrorCode.GRAPH_REUSE,
        )
    seen.add(identity)
    active.add(identity)
    _claim_export_node(state)

    if type(line.moves) is not list:
        raise GameTreeSerializationError(
            "variation moves must be a list",
            code=GameTreeErrorCode.INVALID_CONTAINER,
        )
    _require_comment_list(line.leading_comments, field_name="leading_comments")
    _require_comment_list(line.trailing_comments, field_name="trailing_comments")
    if line.result is not None and (
        not isinstance(line.result, str) or line.result not in RESULTS
    ):
        raise GameTreeSerializationError(
            "variation result must be a canonical PGN result",
            code=GameTreeErrorCode.INVALID_LINE,
        )

    for node in line.moves:
        if not isinstance(node, MoveNode):
            raise GameTreeSerializationError(
                "variation moves must contain MoveNode values",
                code=GameTreeErrorCode.INVALID_MOVE,
            )
        node_identity = id(node)
        if node_identity in seen:
            raise GameTreeSerializationError(
                "GameTree reuses one MoveNode in multiple locations",
                code=GameTreeErrorCode.GRAPH_REUSE,
            )
        seen.add(node_identity)
        _claim_export_node(state)
        _validate_san(node.san)
        if node.move_number is not None and (
            not isinstance(node.move_number, str)
            or not MOVE_NUMBER_TOKEN_RE.fullmatch(node.move_number)
        ):
            raise GameTreeSerializationError(
                "move_number must be a canonical PGN move-number token",
                code=GameTreeErrorCode.INVALID_MOVE,
            )
        _validate_nags(node.nags)
        _require_comment_list(node.comments_before, field_name="comments_before")
        _require_comment_list(node.comments_after, field_name="comments_after")
        if type(node.variations) is not list:
            raise GameTreeSerializationError(
                "move variations must be a list",
                code=GameTreeErrorCode.INVALID_CONTAINER,
            )
        for variation in node.variations:
            _validate_line_for_serialization(
                variation,
                depth=depth + 1,
                state=state,
            )

    active.remove(identity)


def _validate_game_for_serialization(game: object) -> None:
    if not isinstance(game, PgnGame):
        raise GameTreeSerializationError(
            "serialize_game requires a PgnGame",
            code=GameTreeErrorCode.INVALID_GAME,
        )
    if type(game.tags) is not dict:
        raise GameTreeSerializationError(
            "game tags must be a dictionary",
            code=GameTreeErrorCode.INVALID_CONTAINER,
        )
    for key, value in game.tags.items():
        if not isinstance(key, str) or not TAG_NAME_RE.fullmatch(key):
            raise GameTreeSerializationError(
                "tag names must match the PGN tag-name grammar",
                code=GameTreeErrorCode.INVALID_TAG,
            )
        if not isinstance(value, str) or "\r" in value or "\n" in value:
            raise GameTreeSerializationError(
                "tag values must be single-line text",
                code=GameTreeErrorCode.INVALID_TAG,
            )
    # Header tags are source evidence. In particular an invalid historical
    # Result header is preserved verbatim and warned about by parse_games;
    # only the effective domain result below must be canonical.
    if type(game.source_index) is not int or game.source_index < 0:
        raise GameTreeSerializationError(
            "source_index must be a non-negative exact integer",
            code=GameTreeErrorCode.INVALID_GAME,
        )
    if type(game.warnings) is not list or any(
        not isinstance(warning, str) for warning in game.warnings
    ):
        raise GameTreeSerializationError(
            "game warnings must be a list of text values",
            code=GameTreeErrorCode.INVALID_CONTAINER,
        )

    state: dict[str, object] = {"seen": set(), "active": set(), "count": 0}
    _validate_line_for_serialization(game.line, depth=0, state=state)
    if game.result not in RESULTS:
        raise GameTreeSerializationError(
            "effective game result must be a canonical PGN result",
            code=GameTreeErrorCode.INVALID_GAME,
        )


def _serialize_line(line: VariationLine, *, include_result: bool = True) -> str:
    parts: list[str] = []
    parts.extend(_serialize_comment(c) for c in line.leading_comments)
    for node in line.moves:
        if node.move_number:
            parts.append(node.move_number)
        parts.extend(_serialize_comment(c) for c in node.comments_before)
        parts.append(node.san)
        parts.extend(node.nags)
        parts.extend(_serialize_comment(c) for c in node.comments_after)
        for variation in node.variations:
            parts.append("(" + _serialize_line(variation, include_result=True) + ")")
    if include_result and line.result:
        parts.append(line.result)
    parts.extend(_serialize_comment(c) for c in line.trailing_comments)
    return " ".join(p for p in parts if p)


def serialize_game(game: PgnGame) -> str:
    _validate_game_for_serialization(game)
    tags = dict(game.tags)
    tags.setdefault("Result", game.result)
    headers = [f'[{k} "{_escape_tag(v)}"]' for k, v in tags.items()]
    return "\n".join(headers) + "\n\n" + _serialize_line(game.line, include_result=True).strip() + "\n"


def serialize_games(games: Iterable[PgnGame]) -> str:
    try:
        snapshot = tuple(games)
    except TypeError as exc:
        raise GameTreeSerializationError(
            "serialize_games requires an iterable of PgnGame values",
            code=GameTreeErrorCode.INVALID_CONTAINER,
        ) from exc
    for game in snapshot:
        _validate_game_for_serialization(game)
    blocks = [serialize_game(game).rstrip() for game in snapshot]
    if not blocks:
        return ""
    return "\n\n".join(blocks) + "\n"
