from __future__ import annotations

"""Loss-aware structural PGN/GameTree model.

The model owns PGN structure, not chess legality. It preserves comments,
NAGs, nested recursive annotation variations (RAVs), common headers and
recoverable malformed source. Chess legality/FEN validation belongs to the
canonical chess core / PGN semantic validation layer.
"""

from dataclasses import dataclass, field
import re
from typing import Iterable, Iterator, Sequence

RESULTS = {"1-0", "0-1", "1/2-1/2", "*"}
SEVEN_TAG_ROSTER = ("Event", "Site", "Date", "Round", "White", "Black", "Result")
SETUP_TAGS = ("SetUp", "FEN")
TAG_RE = re.compile(r'^\s*\[([A-Za-z0-9_]+)\s+"((?:\\.|[^"\\])*)"\]\s*$')
MOVE_NUMBER_RE = re.compile(r"^(\d+)\.(\.\.)?$")
MOVE_PREFIX_RE = re.compile(r"^(\d+\.{1,3})(.+)$")
SYMBOLIC_NAG_SUFFIX_RE = re.compile(r"^(.*?)(!!|\?\?|!\?|\?!|!|\?)$")
NUMERIC_NAG_RE = re.compile(r"^\$([0-9]{1,3})$")


@dataclass(slots=True, frozen=True)
class PgnDiagnostic:
    code: str
    message: str
    severity: str = "warning"
    token_index: int | None = None


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
    unsupported_tokens: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PgnGame:
    tags: dict[str, str] = field(default_factory=dict)
    line: VariationLine = field(default_factory=VariationLine)
    source_index: int = 0
    warnings: list[str] = field(default_factory=list)
    diagnostics: list[PgnDiagnostic] = field(default_factory=list)
    escape_lines: list[str] = field(default_factory=list)

    @property
    def result(self) -> str:
        return self.line.result or self.tags.get("Result", "*")

    def iter_moves(self, *, recursive: bool = False) -> Iterator[MoveNode]:
        yield from iter_line_moves(self.line, recursive=recursive)

    @property
    def ply_count(self) -> int:
        return sum(1 for _ in self.iter_moves(recursive=False))


@dataclass(slots=True)
class _Token:
    kind: str
    value: str
    index: int = 0


def _unescape_tag(value: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(value):
        if value[i] == "\\" and i + 1 < len(value):
            out.append(value[i + 1])
            i += 2
        else:
            out.append(value[i])
            i += 1
    return "".join(out)


def _escape_tag(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', r'\"')


def _split_symbolic_nag(value: str) -> tuple[str, str | None]:
    match = SYMBOLIC_NAG_SUFFIX_RE.fullmatch(value)
    if not match or not match.group(1):
        return value, None
    return match.group(1), match.group(2)


def tokenize_movetext(text: str) -> list[_Token]:
    """Tokenize movetext without interpreting chess legality.

    The tokenizer is recovery-oriented: malformed comments/unknown dollar
    sequences produce explicit warning/unsupported tokens instead of dropping
    source silently.
    """
    out: list[_Token] = []
    i = 0
    n = len(text)
    token_index = 0

    def emit(kind: str, value: str) -> None:
        nonlocal token_index
        out.append(_Token(kind, value, token_index))
        token_index += 1

    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
            continue
        if c == "%" and (i == 0 or text[i - 1] == "\n"):
            j = text.find("\n", i + 1)
            if j < 0:
                j = n
            emit("ESCAPE", text[i:j].rstrip("\r"))
            i = j
            continue
        if c == "{":
            j = i + 1
            while j < n and text[j] != "}":
                j += 1
            if j >= n:
                emit("COMMENT_BRACE", text[i + 1 :])
                emit("WARNING", "unterminated brace comment")
                break
            emit("COMMENT_BRACE", text[i + 1 : j])
            i = j + 1
            continue
        if c == "}":
            emit("UNSUPPORTED", "}")
            emit("WARNING", "unmatched closing brace")
            i += 1
            continue
        if c == ";":
            j = text.find("\n", i + 1)
            if j < 0:
                j = n
            emit("COMMENT_SEMI", text[i + 1 : j].rstrip("\r"))
            i = j
            continue
        if c == "(":
            emit("LPAREN", c)
            i += 1
            continue
        if c == ")":
            emit("RPAREN", c)
            i += 1
            continue
        if c == "$":
            j = i + 1
            while j < n and text[j].isdigit():
                j += 1
            value = text[i:j]
            if j > i + 1 and NUMERIC_NAG_RE.fullmatch(value):
                emit("NAG", value)
                i = j
                continue
            j = i + 1
            while j < n and not text[j].isspace() and text[j] not in "{};()":
                j += 1
            emit("UNSUPPORTED", text[i:j])
            emit("WARNING", f"invalid NAG token {text[i:j]}")
            i = j
            continue

        j = i
        while j < n and not text[j].isspace() and text[j] not in "{};()":
            j += 1
        value = text[i:j]
        if not value:
            i += 1
            continue

        if value in RESULTS:
            emit("RESULT", value)
            i = j
            continue
        if MOVE_NUMBER_RE.fullmatch(value) or re.fullmatch(r"\d+\.{1,3}", value):
            emit("MOVE_NUMBER", value)
            i = j
            continue
        if value in {"!", "?", "!!", "??", "!?", "?!"}:
            emit("NAG_SYMBOL", value)
            i = j
            continue

        prefix = MOVE_PREFIX_RE.match(value)
        if prefix:
            emit("MOVE_NUMBER", prefix.group(1))
            value = prefix.group(2)

        san, suffix = _split_symbolic_nag(value)
        if san:
            emit("SAN", san)
        if suffix:
            emit("NAG_SYMBOL", suffix)
        i = j
    return out


def _add_diag(
    diagnostics: list[PgnDiagnostic],
    warnings: list[str],
    code: str,
    message: str,
    *,
    severity: str = "warning",
    token_index: int | None = None,
) -> None:
    diagnostics.append(PgnDiagnostic(code, message, severity, token_index))
    warnings.append(message)


def _parse_line(
    tokens: Sequence[_Token],
    pos: int = 0,
    *,
    nested: bool = False,
) -> tuple[VariationLine, int, list[str], list[PgnDiagnostic], list[str]]:
    line = VariationLine()
    warnings: list[str] = []
    diagnostics: list[PgnDiagnostic] = []
    escape_lines: list[str] = []
    pending_number: str | None = None
    pending_comments: list[Comment] = []
    last: MoveNode | None = None

    while pos < len(tokens):
        tok = tokens[pos]
        if tok.kind == "WARNING":
            _add_diag(diagnostics, warnings, "token-warning", tok.value, token_index=tok.index)
            pos += 1
            continue
        if tok.kind == "ESCAPE":
            escape_lines.append(tok.value)
            pos += 1
            continue
        if tok.kind == "UNSUPPORTED":
            line.unsupported_tokens.append(tok.value)
            _add_diag(
                diagnostics,
                warnings,
                "unsupported-token",
                f"preserved unsupported token {tok.value}",
                token_index=tok.index,
            )
            pos += 1
            continue
        if tok.kind == "RPAREN":
            if nested:
                break
            _add_diag(
                diagnostics,
                warnings,
                "unmatched-rparen",
                "unmatched closing parenthesis",
                token_index=tok.index,
            )
            line.unsupported_tokens.append(tok.value)
            pos += 1
            continue
        if tok.kind == "LPAREN":
            pos += 1
            child, pos, child_warnings, child_diags, child_escape = _parse_line(tokens, pos, nested=True)
            warnings.extend(child_warnings)
            diagnostics.extend(child_diags)
            escape_lines.extend(child_escape)
            if pos < len(tokens) and tokens[pos].kind == "RPAREN":
                pos += 1
            else:
                _add_diag(diagnostics, warnings, "unterminated-rav", "unterminated variation")
            if last is not None:
                last.variations.append(child)
            else:
                _add_diag(diagnostics, warnings, "orphan-rav", "variation has no preceding move")
                line.leading_comments.extend(child.leading_comments)
                line.trailing_comments.extend(child.trailing_comments)
                line.unsupported_tokens.append("(" + _serialize_line(child, include_result=True) + ")")
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
            if pending_number is not None:
                _add_diag(
                    diagnostics,
                    warnings,
                    "duplicate-move-number",
                    f"move number {pending_number} replaced by {tok.value}",
                    token_index=tok.index,
                )
            pending_number = tok.value
            pos += 1
            continue
        if tok.kind in {"NAG", "NAG_SYMBOL"}:
            if last is None:
                _add_diag(
                    diagnostics,
                    warnings,
                    "orphan-nag",
                    f"orphan annotation {tok.value}",
                    token_index=tok.index,
                )
                line.unsupported_tokens.append(tok.value)
            else:
                last.nags.append(tok.value)
            pos += 1
            continue
        if tok.kind == "RESULT":
            if line.result is not None:
                _add_diag(
                    diagnostics,
                    warnings,
                    "duplicate-result",
                    f"duplicate result {tok.value}",
                    token_index=tok.index,
                )
            line.result = tok.value
            pos += 1
            if nested:
                break
            continue
        if tok.kind == "SAN":
            if line.result is not None:
                _add_diag(
                    diagnostics,
                    warnings,
                    "movetext-after-result",
                    f"move token after result: {tok.value}",
                    token_index=tok.index,
                )
            node = MoveNode(tok.value, move_number=pending_number, comments_before=pending_comments)
            pending_number = None
            pending_comments = []
            line.moves.append(node)
            last = node
            pos += 1
            continue
        _add_diag(
            diagnostics,
            warnings,
            "unknown-token",
            f"unknown token {tok.kind}:{tok.value}",
            token_index=tok.index,
        )
        line.unsupported_tokens.append(tok.value)
        pos += 1

    if pending_comments:
        if line.moves:
            line.trailing_comments.extend(pending_comments)
        else:
            line.leading_comments.extend(pending_comments)
    if pending_number is not None:
        line.unsupported_tokens.append(pending_number)
        _add_diag(diagnostics, warnings, "orphan-move-number", f"orphan move number {pending_number}")
    return line, pos, warnings, diagnostics, escape_lines


def _line_is_tag(line: str) -> tuple[str, str] | None:
    match = TAG_RE.match(line)
    if not match:
        return None
    return match.group(1), _unescape_tag(match.group(2))


def _split_games(text: str) -> list[tuple[dict[str, str], str, list[str], list[PgnDiagnostic]]]:
    """Split a PGN collection while respecting movetext comments."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    games: list[tuple[dict[str, str], str, list[str], list[PgnDiagnostic]]] = []
    tags: dict[str, str] = {}
    moves: list[str] = []
    escape_lines: list[str] = []
    diagnostics: list[PgnDiagnostic] = []
    seen_movetext = False
    brace_depth = 0

    def flush() -> None:
        nonlocal tags, moves, escape_lines, diagnostics, seen_movetext, brace_depth
        if tags or any(x.strip() for x in moves) or escape_lines:
            games.append((dict(tags), "\n".join(moves).strip(), list(escape_lines), list(diagnostics)))
        tags = {}
        moves = []
        escape_lines = []
        diagnostics = []
        seen_movetext = False
        brace_depth = 0

    for line_no, line in enumerate(lines, start=1):
        stripped = line.lstrip()
        if not seen_movetext and stripped.startswith("%"):
            escape_lines.append(stripped)
            continue

        tag = _line_is_tag(line) if brace_depth == 0 else None
        if tag:
            if seen_movetext:
                flush()
            key, value = tag
            if key in tags:
                diagnostics.append(
                    PgnDiagnostic(
                        "duplicate-tag",
                        f"duplicate tag {key}; last value preserved",
                        "warning",
                        line_no,
                    )
                )
            tags[key] = value
            continue

        if line.strip():
            seen_movetext = True
        if seen_movetext or moves:
            moves.append(line)

        in_semicolon = False
        escaped = False
        for ch in line:
            if escaped:
                escaped = False
                continue
            if ch == "\\" and brace_depth:
                escaped = True
                continue
            if in_semicolon:
                break
            if ch == ";" and brace_depth == 0:
                in_semicolon = True
                break
            if ch == "{" and not in_semicolon:
                brace_depth += 1
            elif ch == "}" and brace_depth:
                brace_depth -= 1
    flush()
    return games


def parse_games(text: str) -> list[PgnGame]:
    games: list[PgnGame] = []
    for index, (tags, movetext, split_escape, split_diags) in enumerate(_split_games(text)):
        tokens = tokenize_movetext(movetext)
        line, pos, warnings, diagnostics, token_escape = _parse_line(tokens)
        diagnostics = list(split_diags) + diagnostics
        warnings = [d.message for d in split_diags] + warnings
        if pos < len(tokens):
            message = f"{len(tokens) - pos} unconsumed token(s)"
            _add_diag(diagnostics, warnings, "unconsumed-tokens", message)
        header_result = tags.get("Result")
        if line.result and header_result and line.result != header_result:
            _add_diag(
                diagnostics,
                warnings,
                "result-mismatch",
                f"header Result {header_result} differs from movetext {line.result}",
            )
        if not line.result:
            line.result = header_result or "*"
        normalized_tags = dict(tags)
        normalized_tags.setdefault("Result", line.result)
        games.append(
            PgnGame(
                tags=normalized_tags,
                line=line,
                source_index=index,
                warnings=warnings,
                diagnostics=diagnostics,
                escape_lines=split_escape + token_escape,
            )
        )
    return games


def parse_game(text: str) -> PgnGame:
    games = parse_games(text)
    if len(games) != 1:
        raise ValueError(f"expected exactly one PGN game, got {len(games)}")
    return games[0]


def _serialize_comment(comment: Comment) -> str:
    text = comment.text.replace("}", r"\}")
    return "{" + text + "}"


def _serialize_line(line: VariationLine, *, include_result: bool = True) -> str:
    parts: list[str] = []
    parts.extend(_serialize_comment(c) for c in line.leading_comments)
    parts.extend(line.unsupported_tokens)
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


def _ordered_tag_items(tags: dict[str, str], result: str) -> list[tuple[str, str]]:
    merged = dict(tags)
    merged["Result"] = result
    ordered: list[tuple[str, str]] = []
    used: set[str] = set()
    for key in SEVEN_TAG_ROSTER + SETUP_TAGS:
        if key in merged:
            ordered.append((key, merged[key]))
            used.add(key)
    for key in sorted(k for k in merged if k not in used):
        ordered.append((key, merged[key]))
    return ordered


def serialize_game(game: PgnGame) -> str:
    headers = [f'[{key} "{_escape_tag(value)}"]' for key, value in _ordered_tag_items(game.tags, game.result)]
    sections: list[str] = []
    if game.escape_lines:
        sections.extend(game.escape_lines)
    if headers:
        sections.append("\n".join(headers))
    movetext = _serialize_line(game.line, include_result=True).strip()
    if movetext:
        sections.append(movetext)
    return "\n\n".join(sections).rstrip() + "\n"


def serialize_games(games: Iterable[PgnGame]) -> str:
    rendered = [serialize_game(game).rstrip() for game in games]
    return "\n\n".join(rendered).rstrip() + ("\n" if rendered else "")


def iter_line_moves(line: VariationLine, *, recursive: bool = False) -> Iterator[MoveNode]:
    for move in line.moves:
        yield move
        if recursive:
            for variation in move.variations:
                yield from iter_line_moves(variation, recursive=True)


def iter_variations(line: VariationLine) -> Iterator[VariationLine]:
    for move in line.moves:
        for variation in move.variations:
            yield variation
            yield from iter_variations(variation)


def structural_signature(game: PgnGame) -> tuple:
    """Return a deterministic semantic signature for loss-aware tests/imports."""

    def comment_sig(comment: Comment) -> tuple[str, str]:
        return comment.text, comment.style

    def line_sig(line: VariationLine) -> tuple:
        return (
            tuple(comment_sig(c) for c in line.leading_comments),
            tuple(
                (
                    move.san,
                    move.move_number,
                    tuple(move.nags),
                    tuple(comment_sig(c) for c in move.comments_before),
                    tuple(comment_sig(c) for c in move.comments_after),
                    tuple(line_sig(v) for v in move.variations),
                )
                for move in line.moves
            ),
            tuple(comment_sig(c) for c in line.trailing_comments),
            line.result,
            tuple(line.unsupported_tokens),
        )

    return (
        tuple(_ordered_tag_items(game.tags, game.result)),
        line_sig(game.line),
        tuple(game.escape_lines),
    )


def canonicalize_games(text: str) -> str:
    """Parse and deterministically re-emit a PGN collection."""
    return serialize_games(parse_games(text))
