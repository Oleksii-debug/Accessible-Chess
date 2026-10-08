from __future__ import annotations

"""Bounded deterministic decoding for legacy Cyrillic book text.

UTF-8 remains authoritative. BOM-declared UTF-16 is accepted deterministically.
Windows-1251 is admitted only after a conservative text-likeness gate so
arbitrary malformed/binary bytes are not silently reinterpreted. This module
performs no filesystem, network, OCR or AI work.
"""

from dataclasses import dataclass


_CP1251_CYRILLIC_BYTES = frozenset(
    (
        *range(0xC0, 0x100),
        0x80,
        0x81,
        0x83,
        0x8A,
        0x8C,
        0x8D,
        0x8E,
        0x8F,
        0x90,
        0x9A,
        0x9C,
        0x9D,
        0x9E,
        0x9F,
        0xA1,
        0xA2,
        0xA3,
        0xA5,
        0xA8,
        0xAA,
        0xAF,
        0xB2,
        0xB3,
        0xB4,
        0xB8,
        0xBA,
        0xBC,
        0xBD,
        0xBE,
        0xBF,
    )
)
_UTF8_BOM = b"\xef\xbb\xbf"
_UTF16_BOMS = (b"\xff\xfe", b"\xfe\xff")
_UTF32_BOMS = (b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")
_HTML_ANCHORS = (
    b"<!doctype",
    b"<html",
    b"<head",
    b"<body",
    b"<?xml",
    b"<p",
    b"<div",
    b"<h1",
    b"<meta",
)
_HTML_CP1251_DECLARATIONS = (
    b"charset=windows-1251",
    b'charset="windows-1251"',
    b"charset='windows-1251'",
    b"charset=cp1251",
    b'charset="cp1251"',
    b"charset='cp1251'",
    b'encoding="windows-1251"',
    b"encoding='windows-1251'",
)


class LegacyTextEncodingError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class DecodedLegacyText:
    text: str
    encoding: str

    @property
    def legacy(self) -> bool:
        return self.encoding == "windows-1251"


def _cyrillic_evidence(payload: bytes) -> tuple[int, int]:
    total = 0
    longest = 0
    current = 0
    for value in payload:
        if value in _CP1251_CYRILLIC_BYTES:
            total += 1
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return total, longest


def _text_like(decoded: str) -> bool:
    if not decoded:
        return False
    controls = 0
    visible_or_space = 0
    for character in decoded:
        code = ord(character)
        if character in "\r\n\t":
            visible_or_space += 1
        elif character.isprintable():
            visible_or_space += 1
        elif code < 32 or 0x7F <= code < 0xA0:
            controls += 1
    if controls > max(2, len(decoded) // 100):
        return False
    return visible_or_space * 100 >= len(decoded) * 95


def _looks_like_windows_1251(payload: bytes, *, html: bool) -> bool:
    if not payload or b"\x00" in payload:
        return False

    total, longest = _cyrillic_evidence(payload)
    if total < 8 or longest < 3:
        return False

    lowered = payload.lower()
    if html:
        declared = any(marker in lowered for marker in _HTML_CP1251_DECLARATIONS)
        structured = any(marker in lowered for marker in _HTML_ANCHORS)
        if not (declared or structured):
            return False

    try:
        decoded = payload.decode("cp1251", errors="strict")
    except UnicodeDecodeError:
        return False
    return _text_like(decoded)


def decode_book_text_bytes(payload: bytes, *, html: bool = False) -> DecodedLegacyText:
    if type(payload) is not bytes:
        raise TypeError("payload must be bytes")
    if payload.startswith(_UTF32_BOMS):
        raise LegacyTextEncodingError("UTF-32 book text is not supported")
    if payload.startswith(_UTF16_BOMS):
        try:
            return DecodedLegacyText(
                payload.decode("utf-16", errors="strict"),
                "utf-16",
            )
        except UnicodeDecodeError as utf16_error:
            raise LegacyTextEncodingError(
                "BOM-declared UTF-16 source is malformed"
            ) from utf16_error
    if payload.startswith(_UTF8_BOM):
        try:
            return DecodedLegacyText(
                payload.decode("utf-8-sig", errors="strict"),
                "utf-8",
            )
        except UnicodeDecodeError as utf8_bom_error:
            raise LegacyTextEncodingError(
                "BOM-declared UTF-8 source is malformed"
            ) from utf8_bom_error
    try:
        return DecodedLegacyText(
            payload.decode("utf-8", errors="strict"),
            "utf-8",
        )
    except UnicodeDecodeError as utf8_error:
        if not _looks_like_windows_1251(payload, html=html):
            raise LegacyTextEncodingError(
                "source is neither valid UTF-8, BOM UTF-16 nor qualified Windows-1251 text"
            ) from utf8_error
        try:
            decoded = payload.decode("cp1251", errors="strict")
        except UnicodeDecodeError as cp_error:
            raise LegacyTextEncodingError(
                "qualified Windows-1251 source could not be decoded"
            ) from cp_error
        return DecodedLegacyText(decoded, "windows-1251")


__all__ = [
    "DecodedLegacyText",
    "LegacyTextEncodingError",
    "decode_book_text_bytes",
]
