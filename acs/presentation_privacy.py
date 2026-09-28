from __future__ import annotations

"""Shared presentation-only privacy helpers.

Filesystem code keeps authoritative local paths internally. Text projected into
WebView/NVDA surfaces must not expose workstation paths. This module is lexical
and host-independent so Windows paths are still recognized when tests run on
Linux and vice versa. It does not alter canonical chess, PGN, Library, Books or
Training state.
"""

import re


# Public HTTP(S) references are content, not local filesystem paths. Keep them as
# indivisible spans so path-looking URL components such as ``/home/`` or ``/C:/``
# are not mistaken for workstation paths.
_PUBLIC_WEB_URL = re.compile(r"(?i)\bhttps?://[^\s\r\n\t]+")

# ``file:`` is considered local only when it actually starts a path/URI. A prose
# label such as ``file: appendix`` or ``file:appendix`` is intentionally not a
# path start.
_FILE_LOCAL_URI = re.compile(
    r"(?i)(?<![\w])file:(?=[/\\]|[a-z]:)[^\r\n\t ]+"
)

# Windows forms covered here:
# - absolute drive paths: C:\\Users\\... or C:/Users/...;
# - drive-relative paths: C:Users\\... and C:Users/...;
# - drive-relative paths whose first component contains spaces when a backslash
#   makes the path intent unambiguous: C:My Documents\\...;
# - UNC and extended/device prefixes: \\\\server\\share, \\\\?\\C:\\..., etc.
#
# A bare prose marker such as ``Chapter C: White to move`` is not a path. Once a
# real local path start is proven, the remainder of that physical line is still
# hidden because valid filesystem components may contain spaces.
_WINDOWS_LOCAL_PATH = re.compile(
    r"(?i)(?<![A-Za-z0-9/])(?:"
    r"[a-z]:[\\/][^\r\n\t]*"
    r"|[a-z]:(?=[^:\r\n\t]{1,260}\\)[^\r\n\t]*"
    r"|[a-z]:[^\s:\\/]+/[^\r\n\t]*"
    r"|\\\\(?:[?.]\\)?[^\\\r\n\t ]+\\[^\r\n\t]*"
    r")"
)

# Internal POSIX roots require a following slash. Bare prose tokens such as
# ``/home`` or ``/var`` are not sufficient evidence of a workstation path.
_POSIX_LOCAL_PATH = re.compile(
    r"(?i)(?<![\w:/])/(?:home|users|tmp|var|private|opt|usr|mnt|etc|srv|run|root|Applications)/"
    r"[^\r\n\t]*"
)


def _redact_non_web_text(text: str, replacement: str) -> str:
    text = _FILE_LOCAL_URI.sub(replacement, text)
    text = _WINDOWS_LOCAL_PATH.sub(replacement, text)
    return _POSIX_LOCAL_PATH.sub(replacement, text)


def redact_local_paths(text: str, replacement: str) -> str:
    """Redact local path fragments from arbitrary user-visible text.

    The helper is presentation-only and deliberately host-independent. Proven
    local file/drive/UNC/internal-POSIX path starts are hidden, while public web
    URLs, safe relative provenance, FEN/SAN, user commands and ordinary prose are
    preserved. Newlines remain intact so semantic content on later lines is not
    discarded.
    """

    if not isinstance(text, str):
        raise TypeError("presentation privacy text must be text")
    if not isinstance(replacement, str) or not replacement:
        raise ValueError("presentation privacy replacement must be non-empty text")

    chunks: list[str] = []
    cursor = 0
    for match in _PUBLIC_WEB_URL.finditer(text):
        chunks.append(_redact_non_web_text(text[cursor : match.start()], replacement))
        chunks.append(match.group(0))
        cursor = match.end()
    chunks.append(_redact_non_web_text(text[cursor:], replacement))
    return "".join(chunks)
