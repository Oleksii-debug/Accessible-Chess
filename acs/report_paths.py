from __future__ import annotations

"""Portable report-only path sanitization.

Internal paths remain available to filesystem code. Serialized reports and
user-facing diagnostics must never depend on the host OS interpretation of a
foreign path syntax. Safe relative provenance may be retained, but absolute
workstation directories must not cross report boundaries.
"""

import os
from typing import Any


def report_safe_name(path: Any) -> str:
    """Return portable relative provenance or a basename for private paths.

    Both slash conventions are recognized lexically, independent of the host
    OS. Absolute POSIX paths, Windows drive paths and UNC paths are reduced to
    their final component. Safe relative paths are preserved with ``/`` so a
    stable provenance such as ``incoming/game.cbh`` is not needlessly lost.
    Any relative traversal component fails closed to the final basename.
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
    is_windows_drive_absolute = (
        len(text) >= 3
        and text[0].isalpha()
        and text[1] == ":"
        and text[2] == "/"
    )
    if is_posix_absolute or is_unc_absolute or is_windows_drive_absolute:
        return basename

    parts = [part for part in text.split("/") if part not in {"", "."}]
    if not parts or ".." in parts:
        return basename
    return "/".join(parts)
