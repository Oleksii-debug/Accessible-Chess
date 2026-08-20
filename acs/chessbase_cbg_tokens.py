"""Bounded, read-only framing evidence for classic ChessBase CBG tokens.

The framing and byte de-obfuscation rules are adapted from ``cbh2pgn`` pinned
at commit 42b3592738062db1f768239e85df1b98cb1cead9. Original cbh2pgn
copyright (c) 2022 Dominik Klein, MIT License.

This module deliberately stops before chess semantics. It identifies the
reference decoder's control-token boundaries and preserves de-obfuscated
candidate values, but it does not identify pieces, construct moves, infer a
position, validate legality, create a GameTree, or claim annotation support.
It also excludes cbh2pgn's GPL ``python-chess`` runtime dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from typing import Literal, cast

from .chessbase_cbg import CbgDecodeError
from .chessbase_cbg_payload_evidence import ClassicCbgMovePayloadEvidence


MAX_CLASSIC_CBG_TOKEN_FRAMES = 100_000
MAX_CLASSIC_CBG_VARIATION_DEPTH = 128

_TWO_BYTE_MARKER = 0x29
_VARIATION_START = 0xDC
_VARIATION_END = 0x0C
_FILLER = 0x9F
_NULL_MOVE_CANDIDATE = 0xAA
_SPECIAL_CODES = frozenset(
    {_TWO_BYTE_MARKER, _VARIATION_START, _VARIATION_END, _FILLER}
)

# Exact 256-byte substitution table used by the pinned MIT reference. Keeping
# this neutral table local prevents the framing layer from depending on its
# GPL chess runtime or importing any move-generation behavior.
_DEOBFUSCATE_2B = bytes.fromhex(
    "a2 95 43 f5 c1 3d 4a 6c 53 83 cc 7c ff ae 68 ad "
    "d1 92 8b 8d 35 81 5e 74 26 8e ab ca fd 9a f3 a0 "
    "a5 15 fc b1 1e ed 30 ea 22 eb a7 cd 4e 6f 2e 24 "
    "32 94 41 8c 6e 58 82 50 bb 02 8a d8 fa 60 de 52 "
    "ba 46 ac 29 9d d7 df 08 21 01 66 a3 f1 19 27 b5 "
    "91 d5 42 0e b4 4c d9 18 5f bc 25 a6 96 04 56 6a "
    "aa 33 1c 2b 73 f0 dd a4 37 d3 c5 10 bf 5a 23 34 "
    "75 5b b8 55 d2 6b 09 3a 57 12 b3 77 48 85 9b 0f "
    "9e c7 c8 a1 7f 7a c0 bd 31 6d f6 3e c3 11 71 ce "
    "7d da a8 54 90 97 1f 44 40 16 c9 e3 2c cb 84 ec "
    "9f 3f 5c e6 76 0b 3c 20 b7 36 00 dc e7 f9 4f f7 "
    "af 06 07 e0 1a 0a a9 4b 0c d6 63 87 89 1d 13 1b "
    "e4 70 05 47 67 7b 2f ee e2 e8 98 0d ef cf c4 f4 "
    "fb b0 17 99 64 f2 d4 2a 03 4d 78 c6 fe 65 86 88 "
    "79 45 3b e5 49 8f 2d b9 be 62 93 14 e9 d0 38 9c "
    "b2 c2 59 5d b6 72 51 f8 28 7e 61 39 e1 db 69 80"
)


class CbgTokenFramingCode(str, Enum):
    """Stable failure codes for unsafe or malformed token evidence."""

    INVALID_EVIDENCE = "invalid_evidence"
    INVALID_LIMIT = "invalid_limit"
    TOKEN_LIMIT = "token_limit"
    VARIATION_DEPTH_LIMIT = "variation_depth_limit"
    TRUNCATED_TWO_BYTE_TOKEN = "truncated_two_byte_token"
    UNMATCHED_VARIATION_END = "unmatched_variation_end"
    UNTERMINATED_VARIATION = "unterminated_variation"
    MISSING_TERMINATOR = "missing_terminator"


class CbgTokenFramingError(CbgDecodeError):
    """Raised when candidate token framing cannot complete safely."""

    def __init__(self, message: str, *, code: CbgTokenFramingCode) -> None:
        super().__init__(message)
        self.code = CbgTokenFramingCode(code)


CbgTokenKind = Literal[
    "one_byte_candidate",
    "two_byte_candidate",
    "variation_start",
    "variation_end",
    "terminal",
    "filler",
    "null_move_candidate",
]


@dataclass(frozen=True, slots=True)
class ClassicCbgTokenFrame:
    """One exact framed token with neutral de-obfuscation evidence."""

    kind: CbgTokenKind
    payload_offset: int
    source_offset: int
    raw_bytes: bytes
    deobfuscated_code: int
    deobfuscated_word: int | None
    processed_counter_before: int
    processed_counter_after: int
    variation_depth_before: int
    variation_depth_after: int

    @property
    def encoded_size(self) -> int:
        return len(self.raw_bytes)


@dataclass(frozen=True, slots=True)
class ClassicCbgTokenFramingEvidence:
    """Complete bounded framing of one exact opaque CBG move payload."""

    game_offset: int
    payload_start_offset: int
    game_end_offset: int
    payload_length: int
    payload_sha256: str
    custom_setup_prefix_consumed: bool
    tokens: tuple[ClassicCbgTokenFrame, ...]
    observed_max_variation_depth: int
    framing_complete: bool = True
    decoder_available: bool = False
    safe_to_import: bool = False

    @property
    def token_count(self) -> int:
        return len(self.tokens)


def _fail(message: str, code: CbgTokenFramingCode) -> None:
    raise CbgTokenFramingError(message, code=code)


def _validate_limit(value: object, *, name: str, hard_maximum: int) -> int:
    if type(value) is not int or value < 0 or value > hard_maximum:
        _fail(
            f"{name} must be an exact integer from 0 through {hard_maximum}",
            CbgTokenFramingCode.INVALID_LIMIT,
        )
    return value


def _validate_evidence(
    evidence: object,
) -> ClassicCbgMovePayloadEvidence:
    if not isinstance(evidence, ClassicCbgMovePayloadEvidence):
        _fail(
            "token framing requires ClassicCbgMovePayloadEvidence",
            CbgTokenFramingCode.INVALID_EVIDENCE,
        )
    evidence = cast(ClassicCbgMovePayloadEvidence, evidence)

    offsets = (
        evidence.game_offset,
        evidence.payload_start_offset,
        evidence.game_end_offset,
    )
    if any(type(value) is not int or value < 0 for value in offsets):
        _fail(
            "CBG payload evidence offsets must be exact non-negative integers",
            CbgTokenFramingCode.INVALID_EVIDENCE,
        )
    if type(evidence.payload_bytes) is not bytes:
        _fail(
            "CBG payload evidence must preserve exact bytes",
            CbgTokenFramingCode.INVALID_EVIDENCE,
        )
    if type(evidence.custom_setup_prefix_consumed) is not bool:
        _fail(
            "CBG setup-prefix evidence must be boolean",
            CbgTokenFramingCode.INVALID_EVIDENCE,
        )
    expected_payload_start = evidence.game_offset + (
        32 if evidence.custom_setup_prefix_consumed else 4
    )
    if (
        evidence.payload_start_offset != expected_payload_start
        or evidence.game_end_offset
        != evidence.payload_start_offset + len(evidence.payload_bytes)
    ):
        _fail(
            "CBG payload evidence span is internally inconsistent",
            CbgTokenFramingCode.INVALID_EVIDENCE,
        )
    if type(evidence.payload_sha256) is not str:
        _fail(
            "CBG payload evidence SHA-256 must be text",
            CbgTokenFramingCode.INVALID_EVIDENCE,
        )
    expected_sha256 = sha256(evidence.payload_bytes).hexdigest()
    if evidence.payload_sha256 != expected_sha256:
        _fail(
            "CBG payload evidence SHA-256 does not match its exact bytes",
            CbgTokenFramingCode.INVALID_EVIDENCE,
        )
    return evidence


def _frame(
    *,
    evidence: ClassicCbgMovePayloadEvidence,
    kind: CbgTokenKind,
    payload_offset: int,
    size: int,
    code: int,
    word: int | None,
    counter_before: int,
    counter_after: int,
    depth_before: int,
    depth_after: int,
) -> ClassicCbgTokenFrame:
    return ClassicCbgTokenFrame(
        kind=kind,
        payload_offset=payload_offset,
        source_offset=evidence.payload_start_offset + payload_offset,
        raw_bytes=evidence.payload_bytes[payload_offset:payload_offset + size],
        deobfuscated_code=code,
        deobfuscated_word=word,
        processed_counter_before=counter_before,
        processed_counter_after=counter_after,
        variation_depth_before=depth_before,
        variation_depth_after=depth_after,
    )


def frame_cbg_move_payload_evidence(
    evidence: ClassicCbgMovePayloadEvidence,
    *,
    max_tokens: int = MAX_CLASSIC_CBG_TOKEN_FRAMES,
    max_variation_depth: int = MAX_CLASSIC_CBG_VARIATION_DEPTH,
) -> ClassicCbgTokenFramingEvidence:
    """Frame one exact payload using only proven control and obfuscation rules.

    A successful result proves byte consumption and balanced variation-control
    markers through the required final terminator. Candidate move bytes remain
    opaque values. Every malformed boundary raises a stable fail-closed error;
    no partial framing result is returned.
    """

    evidence = _validate_evidence(evidence)
    max_tokens = _validate_limit(
        max_tokens,
        name="max_tokens",
        hard_maximum=MAX_CLASSIC_CBG_TOKEN_FRAMES,
    )
    max_variation_depth = _validate_limit(
        max_variation_depth,
        name="max_variation_depth",
        hard_maximum=MAX_CLASSIC_CBG_VARIATION_DEPTH,
    )

    payload = evidence.payload_bytes
    frames: list[ClassicCbgTokenFrame] = []
    offset = 0
    processed_counter = 0
    variation_depth = 0
    observed_max_depth = 0

    while offset < len(payload):
        if len(frames) >= max_tokens:
            _fail(
                f"CBG token framing exceeds configured bound {max_tokens}",
                CbgTokenFramingCode.TOKEN_LIMIT,
            )

        counter_before = processed_counter
        depth_before = variation_depth
        code = (payload[offset] - processed_counter) & 0xFF

        # The pinned algorithm increments this counter for every non-special
        # one-byte value, including 0xAA. The two-byte marker performs its own
        # single increment only after both operand bytes are de-obfuscated.
        counter_after_code = processed_counter
        if code not in _SPECIAL_CODES:
            counter_after_code = (processed_counter + 1) & 0xFF

        if code == _TWO_BYTE_MARKER:
            if len(payload) - offset < 3:
                _fail(
                    f"two-byte CBG token at payload offset {offset} is truncated",
                    CbgTokenFramingCode.TRUNCATED_TWO_BYTE_TOKEN,
                )
            high = _DEOBFUSCATE_2B[
                (payload[offset + 1] - processed_counter) & 0xFF
            ]
            low = _DEOBFUSCATE_2B[
                (payload[offset + 2] - processed_counter) & 0xFF
            ]
            processed_counter = (processed_counter + 1) & 0xFF
            frames.append(
                _frame(
                    evidence=evidence,
                    kind="two_byte_candidate",
                    payload_offset=offset,
                    size=3,
                    code=code,
                    word=(high << 8) | low,
                    counter_before=counter_before,
                    counter_after=processed_counter,
                    depth_before=depth_before,
                    depth_after=variation_depth,
                )
            )
            offset += 3
            continue

        processed_counter = counter_after_code
        is_last_byte = offset == len(payload) - 1

        if code == _VARIATION_END and is_last_byte:
            if variation_depth:
                _fail(
                    "CBG payload terminates with an open variation",
                    CbgTokenFramingCode.UNTERMINATED_VARIATION,
                )
            kind: CbgTokenKind = "terminal"
            depth_after = variation_depth
        elif code == _VARIATION_START:
            if variation_depth >= max_variation_depth:
                _fail(
                    "CBG variation nesting exceeds configured depth "
                    f"{max_variation_depth} at payload offset {offset}",
                    CbgTokenFramingCode.VARIATION_DEPTH_LIMIT,
                )
            variation_depth += 1
            observed_max_depth = max(observed_max_depth, variation_depth)
            kind = "variation_start"
            depth_after = variation_depth
        elif code == _VARIATION_END:
            if variation_depth == 0:
                _fail(
                    f"CBG variation end at payload offset {offset} has no opener",
                    CbgTokenFramingCode.UNMATCHED_VARIATION_END,
                )
            variation_depth -= 1
            kind = "variation_end"
            depth_after = variation_depth
        elif code == _FILLER:
            kind = "filler"
            depth_after = variation_depth
        elif code == _NULL_MOVE_CANDIDATE:
            kind = "null_move_candidate"
            depth_after = variation_depth
        else:
            kind = "one_byte_candidate"
            depth_after = variation_depth

        frames.append(
            _frame(
                evidence=evidence,
                kind=kind,
                payload_offset=offset,
                size=1,
                code=code,
                word=None,
                counter_before=counter_before,
                counter_after=processed_counter,
                depth_before=depth_before,
                depth_after=depth_after,
            )
        )
        offset += 1

        if kind == "terminal":
            return ClassicCbgTokenFramingEvidence(
                game_offset=evidence.game_offset,
                payload_start_offset=evidence.payload_start_offset,
                game_end_offset=evidence.game_end_offset,
                payload_length=evidence.payload_length,
                payload_sha256=evidence.payload_sha256,
                custom_setup_prefix_consumed=evidence.custom_setup_prefix_consumed,
                tokens=tuple(frames),
                observed_max_variation_depth=observed_max_depth,
            )

    if variation_depth:
        _fail(
            f"CBG payload ends with {variation_depth} open variation(s)",
            CbgTokenFramingCode.UNTERMINATED_VARIATION,
        )
    _fail(
        "CBG payload does not end with the required terminator",
        CbgTokenFramingCode.MISSING_TERMINATOR,
    )
