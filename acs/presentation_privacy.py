from __future__ import annotations

"""Shared presentation-only privacy helpers.

Filesystem code keeps authoritative local paths internally. Text projected into
WebView/NVDA surfaces must not expose workstation paths. This module is lexical
and host-independent so Windows paths are still recognized when tests run on
Linux and vice versa. It does not alter canonical chess, PGN, Library, Books or
Training state.
"""

import re


_FILE_LOCAL_URI = re.compile(r"(?i)(?<![\w])file:(?://)?[^\r\n\t ]*")
_WINDOWS_LOCAL_PATH = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:"
    r"[a-z]:[^\r\n\t]*"
    r"|\\\\(?:[?.]\\)?[^\\\r\n\t]+\\[^\r\n\t]*"
    r")"
)
_POSIX_LOCAL_PATH = re.compile(
    r"(?i)(?<![\w])/(?:home|users|tmp|var|private|opt|usr|mnt|etc|srv|run|root|Applications)"
    r"(?:/|\b)[^\r\n\t]*"
)


def redact_local_paths(text: str, replacement: str) -> str:
    """Redact local path fragments from arbitrary user-visible text.

    The matcher is deliberately privacy-first. Once an unquoted drive/UNC/POSIX
    workstation path begins, the remainder of that physical line is treated as
    potentially path-bearing because local path components may legally contain
    spaces. Newlines remain intact so later semantic text is not discarded.

    Safe relative provenance (``incoming/game.pgn``), web URLs, chess notation,
    FEN and user commands such as ``/help`` are not path starts and remain
    unchanged.
    """

    if not isinstance(text, str):
        raise TypeError("presentation privacy text must be text")
    if not isinstance(replacement, str) or not replacement:
        raise ValueError("presentation privacy replacement must be non-empty text")

    text = _FILE_LOCAL_URI.sub(replacement, text)
    text = _WINDOWS_LOCAL_PATH.sub(replacement, text)
    return _POSIX_LOCAL_PATH.sub(replacement, text)
