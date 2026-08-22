from __future__ import annotations

"""Portable report-only path sanitization.

Internal paths remain available to filesystem code.  Serialized reports and
user-facing diagnostics must never depend on the host OS interpretation of a
foreign path syntax, because a Windows path is a single filename to POSIX
``pathlib.Path`` and vice versa.
"""

import os
from typing import Any


def report_safe_name(path: Any) -> str:
    """Return only the final path component for either slash convention.

    The function is deliberately lexical: it never resolves, stats, opens or
    normalizes against the local filesystem.  Both ``/`` and ``\\`` are treated
    as separators so Windows-formatted provenance is safe when serialized on
    POSIX runners and POSIX-formatted provenance is safe on Windows.
    """

    try:
        raw = os.fspath(path)
    except TypeError:
        raw = str(path)
    if isinstance(raw, bytes):
        raw = os.fsdecode(raw)
    text = str(raw).replace("\\", "/").rstrip("/")
    if not text:
        return "source"
    name = text.rsplit("/", 1)[-1]
    if name in {"", ".", ".."} or name.endswith(":"):
        return "source"
    return name
