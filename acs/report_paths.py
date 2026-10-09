from __future__ import annotations

"""Portable report-only path sanitization.

Internal paths remain available to filesystem code. Serialized reports and
user-facing diagnostics must never depend on the host OS interpretation of a
foreign path syntax. Safe relative provenance may be retained, but absolute
workstation directories must not cross report boundaries.
"""

import os
import unicodedata
from typing import Any
from urllib.parse import unquote, urlsplit


_UNSAFE_REPORT_PATH_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Zl", "Zp"})


def _has_unsafe_report_text(text: str) -> bool:
    return any(
        unicodedata.category(character) in _UNSAFE_REPORT_PATH_CATEGORIES
        for character in text
    )


def _report_safe_path_text(text: str) -> str:
    text = text.replace("\\", "/").rstrip("/")
    if not text or _has_unsafe_report_text(text):
        return "source"

    is_windows_drive_path = (
        len(text) >= 2
        and text[0].isalpha()
        and text[1] == ":"
    )
    private_text = text[2:] if is_windows_drive_path else text
    basename = private_text.rsplit("/", 1)[-1]
    if basename in {"", ".", ".."} or basename.endswith(":"):
        return "source"

    is_posix_absolute = text.startswith("/")
    is_unc_absolute = text.startswith("//")
    if is_posix_absolute or is_unc_absolute or is_windows_drive_path:
        return basename

    parts = [part for part in text.split("/") if part not in {"", "."}]
    if not parts or ".." in parts:
        return basename
    return "/".join(parts)


def report_safe_name(path: Any) -> str:
    """Return portable relative provenance or a basename for private paths.

    Both slash conventions are recognized lexically, independent of the host
    OS. Absolute POSIX paths, Windows drive paths, UNC paths and local ``file:``
    URIs are reduced to their final component. Safe relative paths are
    preserved with ``/`` so stable provenance such as ``incoming/game.cbh`` is
    not needlessly lost. Any relative traversal component or report-control
    text fails closed. Percent-encoded local-file URI text is decoded before
    validation so encoded separators or controls cannot bypass the boundary.
    """

    try:
        raw = os.fspath(path)
    except TypeError:
        raw = str(path)
    if isinstance(raw, bytes):
        raw = os.fsdecode(raw)

    text = str(raw)
    if text[:5].casefold() == "file:":
        try:
            parsed = urlsplit(text)
            if parsed.scheme.casefold() != "file":
                return "source"
            text = unquote(parsed.path, encoding="utf-8", errors="strict")
        except (UnicodeDecodeError, ValueError):
            return "source"

    return _report_safe_path_text(text)
