from __future__ import annotations

"""Independent real-corpus oracle for D06 nested-comment recovery.

The workflow supplies an exact, transient Project Gutenberg HTML download.  This
evidence helper extracts the published PGN 73 region only; Product parsing is
performed exclusively by the canonical D06 ``parse_pgn_text`` boundary.
"""

import argparse
from hashlib import sha256
from html import unescape
from pathlib import Path
import re

from acs.gametree_legality import validate_game_legality
from acs.pgn_roundtrip import PgnRoundTripError, parse_pgn_text, serialize_pgn_text


_START_ANCHOR_RE = re.compile(r'<a\b[^>]*(?:name|id)="PGN_73"[^>]*>', re.IGNORECASE)
_STOP_ANCHOR_RE = re.compile(r'<a\b[^>]*(?:name|id)="PGN_74"[^>]*>', re.IGNORECASE)
_PARAGRAPH_RE = re.compile(r'<p\b[^>]*>(.*?)</p\s*>', re.IGNORECASE | re.DOTALL)
_BREAK_RE = re.compile(r'<br\s*/?>', re.IGNORECASE)
_TAG_RE = re.compile(r'<[^>]+>')
_RECOVERY_WARNING = "nested brace comment delimiters normalized to parentheses"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def extract_pgn_73(source: str) -> str:
    start = _START_ANCHOR_RE.search(source)
    stop = _STOP_ANCHOR_RE.search(source, start.end() if start else 0)
    require(start is not None and stop is not None, "real book PGN 73/74 anchors were not found")
    assert start is not None and stop is not None
    paragraph = _PARAGRAPH_RE.search(source, start.end(), stop.start())
    require(paragraph is not None, "real book PGN 73 paragraph was not found")
    assert paragraph is not None
    visible = _BREAK_RE.sub("\n", paragraph.group(1))
    visible = unescape(_TAG_RE.sub("", visible)).strip()
    require('[White "Pindar"]' in visible, "real book PGN 73 White identity changed")
    require(
        '[Black "Montgomery, H. P."]' in visible,
        "real book PGN 73 Black identity changed",
    )
    require(
        "the Black {K. B.} is brought into play" in " ".join(visible.split()),
        "real book nested editorial delimiter evidence changed",
    )
    return visible


def run(source_path: Path, expected_sha256: str) -> None:
    raw = source_path.read_bytes()
    digest = sha256(raw).hexdigest()
    print(f"REAL_BOOK_SOURCE_BYTES={len(raw)}")
    print(f"REAL_BOOK_SOURCE_SHA256={digest}")
    require(digest == expected_sha256, "real book source SHA-256 changed")
    try:
        source = raw.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise SystemExit("real book source is no longer strict UTF-8") from exc

    candidate = extract_pgn_73(source)
    print(f"REAL_BOOK_PGN_73_CHARS={len(candidate)}")

    try:
        parse_pgn_text(candidate, strict=True)
    except PgnRoundTripError:
        pass
    else:
        raise SystemExit("real malformed source unexpectedly bypassed strict recovery policy")

    games = parse_pgn_text(candidate, strict=False)
    require(len(games) == 1, "real book PGN 73 did not recover as exactly one game")
    game = games[0]
    require(game.tags.get("White") == "Pindar", "recovered White identity changed")
    require(game.tags.get("Black") == "Montgomery, H. P.", "recovered Black identity changed")
    require(game.result == "0-1", "recovered real game result changed")
    require(len(game.line.moves) == 68, "recovered real game ply count changed")
    require(game.warnings == [_RECOVERY_WARNING], "recovery warning contract changed")

    comments = [
        comment.text
        for move in game.line.moves
        for comment in move.comments_before + move.comments_after
    ]
    require(
        any("Black (K. B.) is brought into play" in " ".join(text.split()) for text in comments),
        "nested historical annotation was not preserved readably",
    )

    legality = validate_game_legality(game)
    require(legality.complete and not legality.issues, "recovered real game is not canonically legal")

    canonical = serialize_pgn_text(games)
    reopened = parse_pgn_text(canonical, strict=True)
    require(len(reopened) == 1, "canonical real game did not reopen exactly once")
    require(len(reopened[0].line.moves) == 68, "canonical reopen changed real game plies")
    require(not reopened[0].warnings, "canonical reopen still requires recovery")

    print("REAL_BOOK_PGN_73_RECOVERY=PASS")
    print("REAL_BOOK_PGN_73_STRICT_SOURCE=REJECTED_AS_RECOVERY_REQUIRED")
    print("REAL_BOOK_PGN_73_CANONICAL_REOPEN=PASS")
    print("REAL_BOOK_PGN_73_LEGAL_PLIES=68")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--expected-sha256", required=True)
    args = parser.parse_args()
    run(args.source, args.expected_sha256)


if __name__ == "__main__":
    main()
