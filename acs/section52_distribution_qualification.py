"""Fail-closed Section 52.6 corpus-policy gate for two Windows release variants.

This module qualifies staged corpus bytes. It does not replace the canonical
package assembler, establish license ownership, or certify a Windows build.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from urllib.parse import urlsplit

SCHEMA = "accessible-chess-section52-corpus-v1"
_SOURCE_SHA = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {
    prefix + str(n) for prefix in ("COM", "LPT") for n in range(1, 10)
}
MAX_FILES = 20000
MAX_SINGLE_FILE = 1024 * 1024 * 1024
MAX_TOTAL = 8 * MAX_SINGLE_FILE


class DistributionQualificationError(ValueError):
    """A staged corpus cannot be transferred or released."""


def _reject() -> None:
    raise DistributionQualificationError("release corpus verification failed")


def _strict_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, value in pairs:
        if name in result:
            _reject()
        result[name] = value
    return result


def _nonfinite(_: str) -> object:
    _reject()


def _relative(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 800:
        _reject()
    if "\\" in value or ":" in value or "\x00" in value:
        _reject()
    token = PurePosixPath(value)
    if token.is_absolute() or str(token) != value:
        _reject()
    for part in token.parts:
        if (part in (".", "..") or part.startswith(".") or part.endswith((" ", "."))
                or part.partition(".")[0].upper() in _RESERVED
                or any(ord(char) < 32 or ord(char) == 127 for char in part)
                or len(part.encode("utf-16-le")) > 480):
            _reject()
    return value


def _https(value: object) -> str:
    if not isinstance(value, str) or not (1 <= len(value) <= 2048):
        _reject()
    if any(ord(char) <= 32 or ord(char) == 127 for char in value):
        _reject()
    try:
        url = urlsplit(value)
        if (url.scheme != "https" or not url.hostname or url.username
                or url.password or url.fragment or url.port is not None):
            _reject()
    except ValueError:
        _reject()
    return value


def _node(path: Path, directory: bool) -> os.stat_result:
    try:
        info = path.lstat()
    except OSError:
        _reject()
    if ((directory and not stat.S_ISDIR(info.st_mode))
            or (not directory and not stat.S_ISREG(info.st_mode))
            or bool(getattr(info, "st_file_attributes", 0) & 0x400)):
        _reject()
    return info


def _snapshot(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _digest(path: Path) -> tuple[str, int]:
    initial = _node(path, directory=False)
    if initial.st_size > MAX_SINGLE_FILE:
        _reject()
    try:
        with path.open("rb") as inp:
            opened = os.fstat(inp.fileno())
            if _snapshot(initial) != _snapshot(opened):
                _reject()
            sha = hashlib.sha256()
            size = 0
            while True:
                chunk = inp.read(1048576)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_SINGLE_FILE:
                    _reject()
                sha.update(chunk)
            if _snapshot(opened) != _snapshot(os.fstat(inp.fileno())):
                _reject()
    except OSError:
        _reject()
    if _snapshot(initial) != _snapshot(_node(path, directory=False)) or size != initial.st_size:
        _reject()
    return sha.hexdigest(), size


def qualify_distribution_corpus(
    *, stage_dir: Path, manifest_path: Path, expected_source_sha: str
) -> dict[str, object]:
    """Return narrow staging evidence without asserting legal or release PASS."""
    if not isinstance(expected_source_sha, str) or not _SOURCE_SHA.fullmatch(expected_source_sha):
        _reject()
    _node(manifest_path, directory=False)
    if manifest_path.stat().st_size > 1048576:
        _reject()
    try:
        doc = json.loads(manifest_path.read_text(encoding="utf-8"),
                         object_pairs_hook=_strict_pairs, parse_constant=_nonfinite)
    except (UnicodeError, ValueError, OSError):
        _reject()
    if (type(doc) is not dict or set(doc) !=
            {"schema", "kind", "source_sha", "assets", "external_links"}
            or doc["schema"] != SCHEMA
            or doc["kind"] not in ("TEST_BUILD", "PUBLIC_RELEASE")
            or doc["source_sha"] != expected_source_sha
            or type(doc["assets"]) is not list
            or type(doc["external_links"]) is not list
            or len(doc["assets"]) > MAX_FILES or len(doc["external_links"]) > MAX_FILES):
        _reject()
    _node(stage_dir, directory=True)
    found: dict[str, Path] = {}
    folded: set[str] = set()
    folded_dirs: set[str] = set()
    total_bytes = 0
    for current, dirs, files in os.walk(stage_dir, followlinks=False,
                                        onerror=lambda error: _reject()):
        _node(Path(current), directory=True)
        for name in dirs:
            path = Path(current) / name
            _node(path, directory=True)
            dir_token = _relative(path.relative_to(stage_dir).as_posix())
            if dir_token.casefold() in folded_dirs:
                _reject()
            folded_dirs.add(dir_token.casefold())
        for name in files:
            path = Path(current) / name
            relative = _relative(path.relative_to(stage_dir).as_posix())
            info = _node(path, directory=False)
            if relative.casefold() in folded:
                _reject()
            folded.add(relative.casefold())
            total_bytes += info.st_size
            if total_bytes > MAX_TOTAL or info.st_size > MAX_SINGLE_FILE:
                _reject()
            found[relative] = path
            if len(found) > MAX_FILES:
                _reject()
    expected: dict[str, str] = {}
    counts = {"PUBLIC_REDISTRIBUTION": 0, "OWNER_TEST_TRANSFER": 0}
    for asset in doc["assets"]:
        if type(asset) is not dict or set(asset) != {
            "path", "sha256", "permission", "source_url", "rights_ref"
        }:
            _reject()
        name = _relative(asset["path"])
        value = asset["sha256"]
        permission = asset["permission"]
        evidence = asset["rights_ref"]
        if (type(value) is not str or not _SHA256.fullmatch(value)
                or permission not in counts or type(evidence) is not str
                or not (1 <= len(evidence) <= 512)):
            _reject()
        _https(asset["source_url"])
        if doc["kind"] == "PUBLIC_RELEASE" and permission != "PUBLIC_REDISTRIBUTION":
            _reject()
        if name not in found or name.casefold() in (x.casefold() for x in expected):
            _reject()
        expected[name] = value
        counts[permission] += 1
    if set(expected) != set(found):
        _reject()
    links: set[str] = set()
    for link in doc["external_links"]:
        if type(link) is not dict or set(link) != {"title", "url"}:
            _reject()
        url = _https(link["url"])
        if (url in links or type(link["title"]) is not str
                or not (1 <= len(link["title"]) <= 160)):
            _reject()
        links.add(url)
    stage_digest = hashlib.sha256()
    byte_count = 0
    for name in sorted(expected):
        actual, size = _digest(found[name])
        if actual != expected[name]:
            _reject()
        byte_count += size
        stage_digest.update(name.encode("utf-8") + b"\0" + actual.encode("ascii") + b"\n")
    return {
        "schema": SCHEMA,
        "kind": doc["kind"],
        "source_sha": expected_source_sha,
        "qualified_asset_count": len(expected),
        "qualified_bytes": byte_count,
        "rights_counts": counts,
        "external_links": len(links),
        "staged_inventory_sha256": stage_digest.hexdigest(),
        "evidence_class": "STAGED_CORPUS_POLICY_ONLY",
        "actual_legal_rights_verified": False,
        "windows_package_verified": False,
        "section52_done": False,
    }
