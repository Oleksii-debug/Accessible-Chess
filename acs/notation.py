from __future__ import annotations

from dataclasses import dataclass
import re


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
    return san.replace("0", "O")


def parse_san(san: str) -> ParsedSan:
    token = str(san).strip()
    if not token:
        raise NotationError("SAN token must not be empty")

    token = _normalise_castling(token)
    if token in {"O-O", "O-O+", "O-O#", "O-O-O", "O-O-O+", "O-O-O#"}:
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

    if piece == "P" and capture and len(disamb) != 1:
        raise NotationError(f"invalid pawn capture SAN: {san!r}")

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

    if profile not in PROFILES:
        raise NotationError(f"unknown notation profile: {profile}")

    token = _normalise_castling(str(san).strip())
    if not token:
        raise NotationError("SAN token must not be empty")
    if profile == "san":
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

    suffix = token[-1] if token[-1:] in {"+", "#"} else None
    if suffix:
        token = token[:-1]

    token = re.sub(r"^([KQRBN])(?=[a-h1-8])", r"\1 ", token)
    token = re.sub(r"([a-h])([1-8])", r"\1 \2", token)
    token = token.replace("x", " captures " if language == "en" else " б’є ")
    token = re.sub(r"\s+", " ", token).strip()

    if suffix:
        token += f", {_SUFFIX_WORDS[language][suffix]}"
    return token
