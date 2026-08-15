from __future__ import annotations

from dataclasses import dataclass
import re


class NotationError(ValueError):
    """Raised when a notation profile or SAN token cannot be formatted."""


PROFILES = {"san", "accessible_compact", "uk_literal", "en_literal"}

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

    # In pawn captures SAN encodes the origin file before x, e.g. exd5.
    if piece == "P" and capture and len(disamb) != 1:
        raise NotationError(f"invalid pawn capture SAN: {san!r}")

    return ParsedSan(piece, disamb, capture, destination, promotion, suffix)


def _format_accessible_compact(token: str) -> str:
    """Render SAN as short screen-reader-friendly tokens without losing meaning.

    The profile intentionally stays close to canonical SAN while separating
    piece letters, files and ranks so consumers can announce ``N f 3`` instead
    of relying on a screen reader to infer how ``Nf3`` should be pronounced.
    SAN operators remain explicit tokens (``x``, ``=``, ``+``, ``#``), making
    the output compact, deterministic and presentation-neutral.
    """

    for castle in ("O-O-O", "O-O"):
        if token.startswith(castle) and token[len(castle):] in {"", "+", "#"}:
            suffix = token[len(castle):]
            return castle if not suffix else f"{castle} {suffix}"

    parsed = parse_san(token)
    parts: list[str] = []
    if parsed.piece != "P":
        parts.append(parsed.piece)

    if parsed.disambiguation:
        parts.extend(parsed.disambiguation)

    if parsed.capture:
        parts.append("x")

    parts.extend(parsed.destination)

    if parsed.promotion:
        parts.extend(["=", parsed.promotion])

    if parsed.suffix:
        parts.append(parsed.suffix)

    return " ".join(parts)


def format_san(san: str, profile: str = "san") -> str:
    """Format a SAN move using one shared presentation-neutral formatter.

    Profiles:
      * ``san``: canonical SAN, except 0-0 is normalised to O-O.
      * ``accessible_compact``: compact SAN tokens with piece/square separation.
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
    if profile == "accessible_compact":
        return _format_accessible_compact(token)

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
            # For pawn captures this is the origin file; for pieces it is SAN
            # disambiguation. The spoken form remains explicit and reversible.
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
