from __future__ import annotations

from dataclasses import dataclass
import re

from .input_limits import MAX_SAN_CHARS


class NotationError(ValueError):
    """Raised when a notation profile or SAN token cannot be formatted."""


PROFILES = {"san", "uk_literal", "en_literal"}

_PIECES = {
    "uk": {
        "K": "король",
        "Q": "ферзь",
        "R": "тура",
        "B": "слон",
        "N": "кінь",
        "P": "пішак",
    },
    "en": {
        "K": "king",
        "Q": "queen",
        "R": "rook",
        "B": "bishop",
        "N": "knight",
        "P": "pawn",
    },
}

_SUFFIX_WORDS = {
    "uk": {"+": "шах", "#": "мат"},
    "en": {"+": "check", "#": "checkmate"},
}

_WORDS = {
    "uk": {
        "takes": "бере",
        "from_file": "з вертикалі",
        "from_rank": "з горизонталі",
        "from_square": "з поля",
        "promotion": "перетворення на",
        "castle_k": "коротка рокіровка",
        "castle_q": "довга рокіровка",
    },
    "en": {
        "takes": "takes",
        "from_file": "from file",
        "from_rank": "from rank",
        "from_square": "from square",
        "promotion": "promotes to",
        "castle_k": "kingside castling",
        "castle_q": "queenside castling",
    },
}

_SAN_RE = re.compile(
    r"^(?P<piece>[KQRBN])?"
    r"(?P<disamb>[a-h1-8]{0,2})"
    r"(?P<capture>x)?"
    r"(?P<dest>[a-h][1-8])"
    r"(?:=(?P<promo>[QRBN]))?"
    r"(?P<suffix>[+#])?$"
)
_CASTLING_TOKENS = {"O-O", "O-O+", "O-O#", "O-O-O", "O-O-O+", "O-O-O#"}


@dataclass(frozen=True)
class ParsedSan:
    piece: str
    disambiguation: str
    capture: bool
    destination: str
    promotion: str | None
    suffix: str | None


def _square_spoken(square: str) -> str:
    return f"{square[0]} {square[1]}"


def _normalise_castling(san: str) -> str:
    # Tolerate the common legacy all-zero spelling, but do not silently repair
    # mixed glyph forms such as ``0-O`` or ``O-0`` into canonical SAN.
    for legacy, canonical in (("0-0-0", "O-O-O"), ("0-0", "O-O")):
        if san.startswith(legacy):
            suffix = san[len(legacy):]
            if suffix in {"", "+", "#"}:
                return canonical + suffix
    return san


def _bounded_san_text(san: str) -> str:
    if type(san) is not str:
        raise NotationError("SAN token must be text")
    if len(san) > MAX_SAN_CHARS:
        raise NotationError("SAN token is too long")
    token = san.strip()
    if not token:
        raise NotationError("SAN token must not be empty")
    return token


def parse_san(san: str) -> ParsedSan:
    token = _bounded_san_text(san)

    token = _normalise_castling(token)
    if token in _CASTLING_TOKENS:
        raise NotationError("castling is handled directly by format_san")

    match = _SAN_RE.fullmatch(token)
    if not match:
        raise NotationError(f"unsupported SAN token: {san!r}")

    piece = match.group("piece") or "P"
    disamb = match.group("disamb") or ""
    capture = bool(match.group("capture"))
    destination = match.group("dest")
    promotion = match.group("promo")
    suffix = match.group("suffix")

    if piece == "P":
        if capture:
            if len(disamb) != 1 or disamb not in "abcdefgh":
                raise NotationError(f"invalid pawn capture SAN: {san!r}")
        elif disamb:
            # Coordinate/long-algebraic forms such as e2e4 and malformed ee4
            # are not SAN and must not silently enter the canonical SAN path.
            raise NotationError(f"invalid pawn move SAN: {san!r}")

        promotion_rank = destination[1] in {"1", "8"}
        if promotion is not None and not promotion_rank:
            raise NotationError(f"invalid pawn promotion SAN: {san!r}")
        if promotion is None and promotion_rank:
            raise NotationError(f"pawn promotion piece is required: {san!r}")
    else:
        # A legal chess position has exactly one king of each colour, so SAN
        # never needs file/rank/source-square disambiguation for a king.  This
        # is a notation-grammar invariant, not a move-legality decision.
        if piece == "K" and disamb:
            raise NotationError(f"king SAN cannot be disambiguated: {san!r}")
        if promotion is not None:
            raise NotationError(f"only pawns can promote in SAN: {san!r}")
        if len(disamb) == 2 and not (
            disamb[0] in "abcdefgh" and disamb[1] in "12345678"
        ):
            raise NotationError(f"invalid SAN disambiguation: {san!r}")

    return ParsedSan(piece, disamb, capture, destination, promotion, suffix)


def format_san(san: str, profile: str = "san") -> str:
    """Format a SAN move using one shared presentation-neutral formatter.

    Profiles:
      * ``san``: return canonical SAN unchanged except 0-0 is normalised to O-O.
      * ``uk_literal``: Ukrainian spoken/literal form suitable for screen readers.
      * ``en_literal``: English spoken/literal form suitable for screen readers.

    This formatter deliberately does not interpret parser command aliases or
    stored chess-data syntax; it formats an already-produced SAN move only.
    """

    if type(profile) is not str or profile not in PROFILES:
        raise NotationError("unknown notation profile")
    token = _normalise_castling(_bounded_san_text(san))
    is_castling = token in _CASTLING_TOKENS
    if profile == "san":
        if not is_castling:
            parse_san(token)
        return token

    lang = "uk" if profile == "uk_literal" else "en"
    words = _WORDS[lang]
    pieces = _PIECES[lang]

    for castle, key in (("O-O-O", "castle_q"), ("O-O", "castle_k")):
        if token.startswith(castle) and token[len(castle):] in {"", "+", "#"}:
            suffix = token[len(castle):] or None
            result = words[key]
            if suffix:
                result += f", {_SUFFIX_WORDS[lang][suffix]}"
            return result

    parsed = parse_san(token)
    parts: list[str] = [pieces[parsed.piece]]

    if parsed.disambiguation:
        dis = parsed.disambiguation
        if len(dis) == 2 and dis[0] in "abcdefgh" and dis[1] in "12345678":
            parts.extend([words["from_square"], _square_spoken(dis)])
        elif len(dis) == 1 and dis in "abcdefgh":
            if parsed.piece == "P" and parsed.capture:
                parts.append(dis)
            else:
                parts.extend([words["from_file"], dis])
        elif len(dis) == 1 and dis in "12345678":
            parts.extend([words["from_rank"], dis])
        else:
            raise NotationError(f"unsupported SAN disambiguation: {dis!r}")

    if parsed.capture:
        parts.append(words["takes"])

    parts.append(_square_spoken(parsed.destination))

    if parsed.promotion:
        parts.extend([words["promotion"], pieces[parsed.promotion]])

    result = " ".join(parts)
    if parsed.suffix:
        result += f", {_SUFFIX_WORDS[lang][parsed.suffix]}"
    return result


def format_accessible_compact_san(san: str, lang: str = "uk") -> str:
    """Return compact SAN with screen-reader-safe piece/file/rank spacing.

    This is the shared compact presentation profile used by move-list/history
    surfaces.  It deliberately keeps SAN piece letters (``N f 3`` rather than
    translating them to words) while spacing coordinates so NVDA does not read
    tokens such as ``Nf3`` or ``Nc6`` as opaque strings.  Literal Ukrainian and
    English profiles remain available through :func:`format_san`.
    """

    if type(lang) is not str:
        raise NotationError("compact SAN language must be text")
    language = "en" if lang == "en" else "uk"
    token = format_san(san, "san")

    for castle, label_uk, label_en in (
        ("O-O-O", "довга рокіровка", "long castle"),
        ("O-O", "коротка рокіровка", "short castle"),
    ):
        if token.startswith(castle) and token[len(castle):] in {"", "+", "#"}:
            suffix = token[len(castle):] or None
            result = label_en if language == "en" else label_uk
            if suffix:
                result += f", {_SUFFIX_WORDS[language][suffix]}"
            return result

    parsed = parse_san(token)
    parts: list[str] = []
    if parsed.piece != "P":
        parts.append(parsed.piece)

    if parsed.disambiguation:
        if len(parsed.disambiguation) == 2:
            parts.extend(parsed.disambiguation)
        else:
            parts.append(parsed.disambiguation)

    if parsed.capture:
        parts.append("captures" if language == "en" else "б’є")

    parts.append(parsed.destination[0])
    destination_rank = parsed.destination[1]
    if parsed.promotion:
        destination_rank += f"={parsed.promotion}"
    parts.append(destination_rank)

    result = " ".join(parts)
    if parsed.suffix:
        result += f", {_SUFFIX_WORDS[language][parsed.suffix]}"
    return result
