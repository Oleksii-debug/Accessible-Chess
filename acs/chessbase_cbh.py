"""Read-only classic ChessBase CBH index record decoding.

This module adapts evidence-backed record layout details from cbh2pgn,
pinned at commit 42b3592738062db1f768239e85df1b98cb1cead9.

Original cbh2pgn copyright (c) 2022 Dominik Klein, MIT License.
Accessible Chess adaptation deliberately excludes cbh2pgn's GPL
``python-chess`` runtime dependency and does not decode CBG move streams here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterator


CBH_RECORD_SIZE = 46
CBH_FILE_HEADER_SIZE = 46

_MASK_IS_GAME = 0x01
_MASK_MARKED_FOR_DELETION = 0x80
_MASK_DAY = 0x1F
_MASK_MONTH = 0x1E0
_MASK_YEAR = 0xFFFE00

_RESULT_CODES = {
    0: "0-1",
    1: "1/2-1/2",
    2: "1-0",
}


class CbhDecodeError(ValueError):
    """Raised when classic CBH bytes are structurally insufficient."""


@dataclass(frozen=True)
class CbhDate:
    year: int
    month: int
    day: int

    @property
    def structurally_valid(self) -> bool:
        """Whether non-zero month/day fields fall in calendar component ranges.

        Zero means "unknown" in the upstream PGN projection and is therefore
        accepted here without inventing a date.
        """

        return (
            self.year >= 0
            and 0 <= self.month <= 12
            and 0 <= self.day <= 31
        )

    def as_pgn_date(self) -> str:
        """Project known components to PGN date syntax without guessing values."""

        if not self.structurally_valid:
            raise CbhDecodeError(
                f"invalid CBH date components: {self.year}-{self.month}-{self.day}"
            )
        year = f"{self.year:04d}" if self.year else "????"
        month = f"{self.month:02d}" if self.month else "??"
        day = f"{self.day:02d}" if self.day else "??"
        return f"{year}.{month}.{day}"


@dataclass(frozen=True)
class ClassicCbhRecord:
    record_index: int
    flags: int
    game_offset: int
    white_player_offset: int
    black_player_offset: int
    tournament_offset: int
    date: CbhDate
    result: str
    round: int
    subround: int
    white_elo: int
    black_elo: int

    @property
    def is_game(self) -> bool:
        return bool(self.flags & _MASK_IS_GAME)

    @property
    def marked_for_deletion(self) -> bool:
        return bool(self.flags & _MASK_MARKED_FOR_DELETION)

    @property
    def eligible_game_record(self) -> bool:
        """Header-level eligibility only; CBG encoding may still be unsupported."""

        return self.is_game and not self.marked_for_deletion


def _require_record(record: bytes) -> bytes:
    if len(record) != CBH_RECORD_SIZE:
        raise CbhDecodeError(
            f"classic CBH record must be exactly {CBH_RECORD_SIZE} bytes; "
            f"got {len(record)}"
        )
    return record


def _u24_be(data: bytes) -> int:
    if len(data) != 3:
        raise CbhDecodeError("expected exactly three bytes for CBH 24-bit integer")
    return int.from_bytes(data, "big", signed=False)


def parse_cbh_record(record: bytes, *, record_index: int) -> ClassicCbhRecord:
    """Decode one 46-byte classic CBH index record into a neutral DTO.

    The function only interprets fields established by the pinned MIT source.
    Unknown/reserved bytes remain uninterpreted. No filesystem writes occur.
    """

    raw = _require_record(record)
    packed_date = _u24_be(raw[24:27])
    date = CbhDate(
        year=(packed_date & _MASK_YEAR) >> 9,
        month=(packed_date & _MASK_MONTH) >> 5,
        day=packed_date & _MASK_DAY,
    )
    return ClassicCbhRecord(
        record_index=record_index,
        flags=raw[0],
        game_offset=int.from_bytes(raw[1:5], "big", signed=False),
        white_player_offset=_u24_be(raw[9:12]),
        black_player_offset=_u24_be(raw[12:15]),
        tournament_offset=_u24_be(raw[15:18]),
        date=date,
        result=_RESULT_CODES.get(raw[27], "*"),
        round=raw[29],
        subround=raw[30],
        white_elo=int.from_bytes(raw[31:33], "big", signed=False),
        black_elo=int.from_bytes(raw[33:35], "big", signed=False),
    )


def read_cbh_file_header(stream: BinaryIO) -> bytes:
    """Read the opaque 46-byte classic CBH file header from a binary stream."""

    header = stream.read(CBH_FILE_HEADER_SIZE)
    if len(header) != CBH_FILE_HEADER_SIZE:
        raise CbhDecodeError(
            f"classic CBH file header must be {CBH_FILE_HEADER_SIZE} bytes; "
            f"got {len(header)}"
        )
    return header


def iter_cbh_records(path: str | Path) -> Iterator[ClassicCbhRecord]:
    """Stream complete classic CBH records after the file header, read-only.

    A trailing partial record is rejected rather than silently ignored. The
    source file is opened as ``rb`` and is never modified.
    """

    source = Path(path)
    with source.open("rb") as stream:
        read_cbh_file_header(stream)
        record_index = 1
        while True:
            raw = stream.read(CBH_RECORD_SIZE)
            if raw == b"":
                return
            if len(raw) != CBH_RECORD_SIZE:
                raise CbhDecodeError(
                    f"trailing partial CBH record at index {record_index}: "
                    f"expected {CBH_RECORD_SIZE} bytes, got {len(raw)}"
                )
            yield parse_cbh_record(raw, record_index=record_index)
            record_index += 1
