"""Preserved Section 39 sixteen-format contract from protected PR #2494.

This is a format identity list for evidence validation, not a claim that any
read/write operation is supported. Capability outcomes remain source-bound.
"""
from __future__ import annotations

FORMATS = (
    "FEN", "SAN", "EPD", "PGN", "ACSDB", "EPUB", "HTML", "TXT",
    "Markdown", "DOCX", "PDF", "CBH", "CBV", "CBF", "2CBH", "CBONE",
)
