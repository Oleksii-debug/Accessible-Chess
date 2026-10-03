from __future__ import annotations

"""Deterministic local decoding for human-authored text chess sources.

This module is intentionally not a universal binary charset guesser. UTF-8 is
authoritative, UTF-16 is admitted only with a BOM, and Windows-1251 fallback is
accepted only when invalid UTF-8 bytes also provide strong text/Cyrillic
evidence. No network, AI model or locale-dependent codec guessing is used.
"""

from dataclasses import dataclass


_CP1251_CYRILLIC_LETTER_BYTES = frozenset((
    *range(0xC0, 0x100),
    0x80, 0x81, 0x83, 0x8A, 0x8C, 0x8D, 0x8E, 0x8F,
    0x90, 0x9A, 0x9C, 0x9D, 0x9E, 0x9F,
    0xA1, 0xA2, 0xA3, 0xA5, 0xA8, 0xAA, 0xAF,
    0xB2, 0xB3, 0xB4, 0xB8, 0xBA, 0xBC, 0xBD, 0xBE, 0xBF,
))
_CP1251_ALLOWED_ASCII_CONTROLS = frozenset({0x09, 0x0A, 0x0D})


@dataclass(frozen=True, slots=True)
class DecodedLocalText:
    text: str
    encoding: str
    transcoded: bool


class LocalTextDecodeError(ValueError):
    pass


def _cp1251_text_evidence(payload: bytes) -> bool:
    if not payload or b"\x00" in payload:
        return False

    # Inspect the entire payload before accepting any positive Cyrillic signal.
    # The former early return on two adjacent letters could admit a binary or
    # malformed source when a disallowed control byte appeared later.
    if any(
        value < 0x20 and value not in _CP1251_ALLOWED_ASCII_CONTROLS
        for value in payload
    ):
        return False

    previous_cyrillic = False
    cyrillic_letters = 0
    adjacent_cyrillic = False
    for value in payload:
        current = value in _CP1251_CYRILLIC_LETTER_BYTES
        if current:
            cyrillic_letters += 1
            if previous_cyrillic:
                adjacent_cyrillic = True
        previous_cyrillic = current

    # Two adjacent letters are strong evidence of prose; four separated letters
    # retain the existing fallback for tag-heavy PGN/text sources.
    return adjacent_cyrillic or cyrillic_letters >= 4


def decode_local_text(payload: bytes) -> DecodedLocalText:
    if type(payload) is not bytes:
        raise TypeError("payload must be bytes")
    if not payload:
        return DecodedLocalText("", "utf-8", False)

    try:
        return DecodedLocalText(payload.decode("utf-8-sig", errors="strict"), "utf-8", False)
    except UnicodeDecodeError:
        pass

    if payload.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            text = payload.decode("utf-16", errors="strict")
        except UnicodeDecodeError as exc:
            raise LocalTextDecodeError("UTF-16 text source is malformed") from exc
        return DecodedLocalText(text, "utf-16", True)

    if _cp1251_text_evidence(payload):
        try:
            text = payload.decode("cp1251", errors="strict")
        except UnicodeDecodeError as exc:
            raise LocalTextDecodeError("Windows-1251 text source is malformed") from exc
        return DecodedLocalText(text, "windows-1251", True)

    raise LocalTextDecodeError("unsupported or ambiguous text encoding")


__all__ = ["DecodedLocalText", "LocalTextDecodeError", "decode_local_text"]
