"""Read-only classic ChessBase CBP player-record decoding.

This module adapts evidence-backed player record layout details from cbh2pgn,
pinned at commit 42b3592738062db1f768239e85df1b98cb1cead9.

Original cbh2pgn copyright (c) 2022 Dominik Klein, MIT License.
Accessible Chess adaptation deliberately excludes cbh2pgn's GPL
``python-chess`` runtime dependency and exposes neutral DTOs only.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


CBP_RECORD_SIZE = 67
_CBP_VERSION_OFFSET = 0x18
_CBP_FIRST_RECORD_BY_VERSION = {
    0: 28,
    4: 32,
}
_LAST_NAME_OFFSET = 9
_LAST_NAME_SIZE = 30
_FIRST_NAME_OFFSET = 39
_FIRST_NAME_SIZE = 20


class CbpDecodeError(ValueError):
    """Raised when classic CBP bytes are unsupported or structurally insufficient."""


@dataclass(frozen=True)
class ClassicCbpPlayer:
    player_no: int
    last_name: str
    first_name: str

    @property
    def pgn_name(self) -> str:
        """Return the upstream-compatible ``Last, First`` PGN projection."""

        return f"{self.last_name}, {self.first_name}"


def _decode_nul_terminated_utf8(field: bytes) -> str:
    """Decode one fixed-width CBP text field without reading beyond its record."""

    return field.split(b"\x00", 1)[0].decode("utf-8", errors="replace")


def _first_record_offset(data: bytes) -> int:
    if len(data) <= _CBP_VERSION_OFFSET:
        raise CbpDecodeError(
            "classic CBP file is too short to contain the version byte at 0x18"
        )
    version = data[_CBP_VERSION_OFFSET]
    try:
        return _CBP_FIRST_RECORD_BY_VERSION[version]
    except KeyError as exc:
        raise CbpDecodeError(f"unsupported classic CBP file version: {version}") from exc


def parse_cbp_player(data: bytes, *, player_no: int) -> ClassicCbpPlayer:
    """Decode one player record from an in-memory classic CBP file image.

    ``player_no`` is the zero-based player number stored by classic CBH index
    records. Only the name fields established by the pinned MIT source are
    interpreted. No filesystem writes occur and unknown fields remain opaque.
    """

    if not isinstance(player_no, int) or isinstance(player_no, bool) or player_no < 0:
        raise CbpDecodeError("player_no must be a non-negative integer")

    record_offset = _first_record_offset(data) + player_no * CBP_RECORD_SIZE
    record_end = record_offset + CBP_RECORD_SIZE
    if record_end > len(data):
        raise CbpDecodeError(
            f"CBP player record {player_no} is truncated or outside the file: "
            f"need bytes [{record_offset}, {record_end}), file size is {len(data)}"
        )

    record = data[record_offset:record_end]
    last_name = _decode_nul_terminated_utf8(
        record[_LAST_NAME_OFFSET:_LAST_NAME_OFFSET + _LAST_NAME_SIZE]
    )
    first_name = _decode_nul_terminated_utf8(
        record[_FIRST_NAME_OFFSET:_FIRST_NAME_OFFSET + _FIRST_NAME_SIZE]
    )
    return ClassicCbpPlayer(
        player_no=player_no,
        last_name=last_name,
        first_name=first_name,
    )


def read_cbp_player(path: str | Path, *, player_no: int) -> ClassicCbpPlayer:
    """Read and decode one classic CBP player record without modifying the source."""

    source = Path(path)
    with source.open("rb") as stream:
        data = stream.read()
    return parse_cbp_player(data, player_no=player_no)
