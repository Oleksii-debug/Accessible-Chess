"""Read-only classic ChessBase CBT tournament-record decoding.

This module adapts evidence-backed tournament record layout details from cbh2pgn,
pinned at commit 42b3592738062db1f768239e85df1b98cb1cead9.

Original cbh2pgn copyright (c) 2022 Dominik Klein, MIT License.
Accessible Chess adaptation deliberately excludes cbh2pgn's GPL
``python-chess`` runtime dependency and exposes neutral DTOs only.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


CBT_RECORD_SIZE = 99
_CBT_VERSION_OFFSET = 0x18
_CBT_FIRST_RECORD_BY_VERSION = {
    0: 28,
    4: 32,
}
_TITLE_OFFSET = 9
_TITLE_SIZE = 40
_SITE_OFFSET = 49
_SITE_SIZE = 30


class CbtDecodeError(ValueError):
    """Raised when classic CBT bytes are unsupported or structurally insufficient."""


@dataclass(frozen=True)
class ClassicCbtTournament:
    tournament_no: int
    event: str
    site: str


def _decode_nul_terminated_utf8(field: bytes) -> str:
    """Decode one fixed-width CBT text field without reading beyond its record."""

    return field.split(b"\x00", 1)[0].decode("utf-8", errors="replace")


def _first_record_offset(data: bytes) -> int:
    if len(data) <= _CBT_VERSION_OFFSET:
        raise CbtDecodeError(
            "classic CBT file is too short to contain the version byte at 0x18"
        )
    version = data[_CBT_VERSION_OFFSET]
    try:
        return _CBT_FIRST_RECORD_BY_VERSION[version]
    except KeyError as exc:
        raise CbtDecodeError(f"unsupported classic CBT file version: {version}") from exc


def parse_cbt_tournament(data: bytes, *, tournament_no: int) -> ClassicCbtTournament:
    """Decode one classic CBT tournament record from an in-memory file image.

    ``tournament_no`` is the zero-based tournament number referenced by classic
    CBH index records. Only event/title and site fields established by the pinned
    MIT source are interpreted. Unknown bytes remain opaque.
    """

    if (
        not isinstance(tournament_no, int)
        or isinstance(tournament_no, bool)
        or tournament_no < 0
    ):
        raise CbtDecodeError("tournament_no must be a non-negative integer")

    record_offset = _first_record_offset(data) + tournament_no * CBT_RECORD_SIZE
    record_end = record_offset + CBT_RECORD_SIZE
    if record_end > len(data):
        raise CbtDecodeError(
            f"CBT tournament record {tournament_no} is truncated or outside the file: "
            f"need bytes [{record_offset}, {record_end}), file size is {len(data)}"
        )

    record = data[record_offset:record_end]
    event = _decode_nul_terminated_utf8(
        record[_TITLE_OFFSET:_TITLE_OFFSET + _TITLE_SIZE]
    )
    site = _decode_nul_terminated_utf8(
        record[_SITE_OFFSET:_SITE_OFFSET + _SITE_SIZE]
    )
    return ClassicCbtTournament(
        tournament_no=tournament_no,
        event=event,
        site=site,
    )


def read_cbt_tournament(
    path: str | Path, *, tournament_no: int
) -> ClassicCbtTournament:
    """Read one classic CBT tournament record without modifying the source."""

    source = Path(path)
    with source.open("rb") as stream:
        data = stream.read()
    return parse_cbt_tournament(data, tournament_no=tournament_no)
