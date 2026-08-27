from __future__ import annotations

"""Portable report-only path sanitization.

Internal paths remain available to filesystem code. User-facing diagnostics and
serialized reports must not expose absolute workstation directories, regardless
of whether the submitted path uses POSIX or Windows separators.
"""

import os
from typing import Any


def report_safe_name(path: Any) -> str:
    """Return portable relative provenance or a basename for private paths.

    Safe relative provenance such as ``incoming/game.pgn`` is retained and
    normalized to ``/``. Absolute POSIX paths, Windows drive-qualified paths
    (including drive-relative ``C:folder/file`` forms), UNC paths, and relative
    traversal fail closed to a basename.
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

    basename = text.rsplit("/", 1)[-1]
    if basename in {"", ".", ".."} or basename.endswith(":"):
        return "source"

    is_posix_absolute = text.startswith("/")
    is_unc_absolute = text.startswith("//")
    is_windows_drive_qualified = (
        len(text) >= 2
        and text[0].isalpha()
        and text[1] == ":"
    )
    if is_posix_absolute or is_unc_absolute or is_windows_drive_qualified:
        return basename

    parts = [part for part in text.split("/") if part not in {"", "."}]
    if not parts or ".." in parts:
        return basename
    return "/".join(parts)
