from __future__ import annotations

"""Loss-preserving structural PGN model for the Stage 2 data core.

This module intentionally separates *structure* from chess legality. It keeps
comments, NAGs and nested RAV branches instead of flattening them. A later
position-linking pass may validate every SAN token against chesscore.Board
without making import destructive when a historical source is damaged.
"""

from dataclasses import dataclass, field
import re
from typing import Iterable

RESULTS = {"1-0", "0-1", "1/2-1/2", "*"}
TAG_RE = re.compile(r'^\s*\[([A-Za-z0-9_]+)\s+"((?:\\.|[^"\\])*)"\]\s*$')
MOVE_NUMBER_RE = re.compile(r"^(\d+)\.(\.\.)?$")


@dataclass(slots=True)
class Comment:
    text: str
    style: str = "brace"


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
            if last is None:
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


def _split_games(text: str) -> list[tuple[dict[str, str], str]]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    games: list[tuple[dict[str, str], str]] = []
    tags: dict[str, str] = {}
    moves: list[str] = []
    seen_movetext = False

    def flush() -> None:
        nonlocal tags, moves, seen_movetext
        if tags or any(x.strip() for x in moves):
            games.append((tags, "\n".join(moves).strip()))
        tags = {}; moves = []; seen_movetext = False

    for line in lines:
        m = TAG_RE.match(line)
        if m:
            if seen_movetext:
                flush()
            tags[m.group(1)] = _unescape_tag(m.group(2))
            continue
        if line.strip():
            seen_movetext = True
        if seen_movetext or moves:
            moves.append(line)
    flush()
    return games


def parse_games(text: str) -> list[PgnGame]:
    games: list[PgnGame] = []
    for index, (tags, movetext) in enumerate(_split_games(text)):
        tokens = tokenize_movetext(movetext)
        line, pos, warnings = _parse_line(tokens)
        if pos < len(tokens):
            warnings.append(f"{len(tokens) - pos} unconsumed token(s)")
        header_result = tags.get("Result")
        if line.result and header_result and line.result != header_result:
            warnings.append(f"header Result {header_result} differs from movetext {line.result}")
        if not line.result:
            line.result = header_result or "*"
        tags = dict(tags)
        tags.setdefault("Result", line.result)
        games.append(PgnGame(tags=tags, line=line, source_index=index, warnings=warnings))
    return games


def _serialize_comment(c: Comment) -> str:
    return "{" + c.text + "}"


def _serialize_line(line: VariationLine, *, include_result: bool = True) -> str:
    parts: list[str] = []
    parts.extend(_serialize_comment(c) for c in line.leading_comments)
    for node in line.moves:
        parts.extend(_serialize_comment(c) for c in node.comments_before)
        if node.move_number:
            parts.append(node.move_number)
        parts.append(node.san)
        parts.extend(node.nags)
        parts.extend(_serialize_comment(c) for c in node.comments_after)
        for variation in node.variations:
            parts.append("(" + _serialize_line(variation, include_result=True) + ")")
    parts.extend(_serialize_comment(c) for c in line.trailing_comments)
    if include_result and line.result:
        parts.append(line.result)
    return " ".join(p for p in parts if p)


def serialize_game(game: PgnGame) -> str:
    tags = dict(game.tags)
    tags["Result"] = game.result
    headers = [f'[{k} "{_escape_tag(v)}"]' for k, v in tags.items()]
    return "\n".join(headers) + "\n\n" + _serialize_line(game.line, include_result=True).strip() + "\n"


def serialize_games(games: Iterable[PgnGame]) -> str:
    return "\n".join(serialize_game(g).rstrip() for g in games).rstrip() + "\n"
