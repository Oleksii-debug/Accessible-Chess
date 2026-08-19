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


class GameTreeErrorCode(str, Enum):
    INVALID_COMMENT_TEXT = "invalid_comment_text"
    UNSUPPORTED_COMMENT_STYLE = "unsupported_comment_style"
    UNREPRESENTABLE_COMMENT = "unrepresentable_comment"


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
        elif value in {"!", "?", "!!", "??", "!?", "?!"}:
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


def _parse_line(tokens: list[_Token], pos: int = 0, *, nested: bool = False) -> tuple[VariationLine, int, list[str]]:
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
            pos += 1
            child, pos, child_warnings = _parse_line(tokens, pos, nested=True)
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
    tags = dict(game.tags)
    tags.setdefault("Result", game.result)
    headers = [f'[{k} "{_escape_tag(v)}"]' for k, v in tags.items()]
    return "\n".join(headers) + "\n\n" + _serialize_line(game.line, include_result=True).strip() + "\n"


def serialize_games(games: Iterable[PgnGame]) -> str:
    blocks = [serialize_game(game).rstrip() for game in games]
    if not blocks:
        return ""
    return "\n\n".join(blocks) + "\n"
