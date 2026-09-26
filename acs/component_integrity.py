from __future__ import annotations

"""Read-only integrity verification for selected protected product components.

This module intentionally does not sign releases, verify Authenticode, update the
application, or mutate/quarantine files.  A caller supplies a trusted SHA-256 for
the manifest (for example from independently authenticated release metadata) and
an exact set of component paths required by an online/provider surface.  Only
those bounded installation files are read and hashed.
"""

from dataclasses import dataclass
from hashlib import sha256
import hmac
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any, Iterable


INTEGRITY_MANIFEST_SCHEMA = "accessible-chess-component-integrity-v1"
_MAX_MANIFEST_BYTES = 64 * 1024
_MAX_COMPONENTS = 512
_DEFAULT_MAX_COMPONENT_BYTES = 512 * 1024 * 1024
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TOP_FIELDS = frozenset({"schema", "components"})
_COMPONENT_FIELDS = frozenset({"path", "sha256"})
_WINDOWS_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


class ComponentIntegrityError(ValueError):
    """Fail-closed error for an untrusted or altered protected component."""


@dataclass(frozen=True, slots=True)
class ComponentDigest:
    path: str
    sha256: str
    size: int


@dataclass(frozen=True, slots=True)
class ComponentIntegrityReport:
    manifest_sha256: str
    components: tuple[ComponentDigest, ...]

    @property
    def verified_paths(self) -> tuple[str, ...]:
        return tuple(component.path for component in self.components)


def verify_protected_components(
    manifest_bytes: bytes,
    *,
    trusted_manifest_sha256: str,
    installation_root: str | os.PathLike[str],
    required_paths: Iterable[str],
    max_component_bytes: int = _DEFAULT_MAX_COMPONENT_BYTES,
) -> ComponentIntegrityReport:
    """Verify exact selected installation components against a trusted manifest.

    Verification is deliberately read-only.  Failure raises
    :class:`ComponentIntegrityError`; callers enabling an online/provider feature
    must treat that as a deny decision rather than attempting repair or deleting
    user content.
    """

    if type(manifest_bytes) is not bytes:
        raise ComponentIntegrityError("component integrity manifest must be bytes")
    if not manifest_bytes or len(manifest_bytes) > _MAX_MANIFEST_BYTES:
        raise ComponentIntegrityError("component integrity manifest has an invalid size")

    trusted_digest = _require_sha256(trusted_manifest_sha256, "trusted manifest digest")
    actual_manifest_digest = sha256(manifest_bytes).hexdigest()
    if not hmac.compare_digest(actual_manifest_digest, trusted_digest):
        raise ComponentIntegrityError("component integrity manifest is not trusted")

    if type(max_component_bytes) is not int or isinstance(max_component_bytes, bool) or max_component_bytes <= 0:
        raise ComponentIntegrityError("max_component_bytes must be a positive integer")

    document = _parse_manifest(manifest_bytes)
    components = _parse_components(document["components"])
    required = _normalize_required_paths(required_paths)
    manifest_paths = tuple(component.path for component in components)
    if manifest_paths != required:
        raise ComponentIntegrityError("component integrity manifest does not exactly cover required protected paths")

    root = Path(installation_root)
    try:
        root = root.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ComponentIntegrityError("installation root is unavailable") from exc
    try:
        root_stat = root.stat()
    except OSError as exc:
        raise ComponentIntegrityError("installation root is unavailable") from exc
    if not stat.S_ISDIR(root_stat.st_mode):
        raise ComponentIntegrityError("installation root is not a directory")

    verified: list[ComponentDigest] = []
    for expected in components:
        verified.append(
            _verify_one_component(
                root,
                expected,
                max_component_bytes=max_component_bytes,
            )
        )

    return ComponentIntegrityReport(
        manifest_sha256=actual_manifest_digest,
        components=tuple(verified),
    )


def _parse_manifest(data: bytes) -> dict[str, Any]:
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ComponentIntegrityError("component integrity manifest is not valid UTF-8") from exc
    try:
        value = json.loads(text, object_pairs_hook=_reject_duplicate_pairs)
    except ComponentIntegrityError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError, RecursionError):
        raise ComponentIntegrityError("component integrity manifest is not valid JSON") from None
    document = _require_exact_mapping(value, _TOP_FIELDS, "component integrity manifest")
    if document["schema"] != INTEGRITY_MANIFEST_SCHEMA:
        raise ComponentIntegrityError("component integrity manifest schema is unsupported")
    return document


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ComponentIntegrityError("component integrity manifest contains a duplicate field")
        result[key] = value
    return result


def _require_exact_mapping(value: Any, fields: frozenset[str], name: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != fields:
        raise ComponentIntegrityError(f"{name} fields are invalid")
    return dict(value)


def _parse_components(value: Any) -> tuple[ComponentDigest, ...]:
    if type(value) is not list or not value or len(value) > _MAX_COMPONENTS:
        raise ComponentIntegrityError("components must be a bounded non-empty list")
    parsed: list[ComponentDigest] = []
    folded: set[str] = set()
    for raw in value:
        entry = _require_exact_mapping(raw, _COMPONENT_FIELDS, "component entry")
        path = _normalize_relative_component_path(entry["path"])
        digest = _require_sha256(entry["sha256"], "component sha256")
        key = path.casefold()
        if key in folded:
            raise ComponentIntegrityError("component paths collide under Windows case folding")
        folded.add(key)
        parsed.append(ComponentDigest(path=path, sha256=digest, size=0))
    ordered = tuple(sorted(parsed, key=lambda item: item.path.casefold()))
    if tuple(parsed) != ordered:
        raise ComponentIntegrityError("component entries must be sorted by path")
    return ordered


def _normalize_required_paths(paths: Iterable[str]) -> tuple[str, ...]:
    if isinstance(paths, (str, bytes)):
        raise ComponentIntegrityError("required_paths must be an iterable of component paths")
    normalized: list[str] = []
    try:
        for index, path in enumerate(paths):
            if index >= _MAX_COMPONENTS:
                raise ComponentIntegrityError("required_paths must be bounded and non-empty")
            normalized.append(_normalize_relative_component_path(path))
    except ComponentIntegrityError:
        raise
    except TypeError as exc:
        raise ComponentIntegrityError("required_paths must be an iterable of component paths") from exc
    if not normalized:
        raise ComponentIntegrityError("required_paths must be bounded and non-empty")
    if len({path.casefold() for path in normalized}) != len(normalized):
        raise ComponentIntegrityError("required protected paths collide under Windows case folding")
    return tuple(sorted(normalized, key=str.casefold))


def _normalize_relative_component_path(value: Any) -> str:
    if type(value) is not str or not value or len(value) > 512:
        raise ComponentIntegrityError("component path must be bounded non-empty text")
    if "\\" in value or "\x00" in value or any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value):
        raise ComponentIntegrityError("component path contains forbidden characters")
    if value.startswith("/") or ":" in value:
        raise ComponentIntegrityError("component path must be relative")
    pure = PurePosixPath(value)
    parts = pure.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ComponentIntegrityError("component path contains traversal or empty segments")
    for part in parts:
        stem = part.rstrip(" .").split(".", 1)[0].casefold()
        if part != part.rstrip(" .") or stem in _WINDOWS_RESERVED:
            raise ComponentIntegrityError("component path is unsafe on Windows")
    normalized = pure.as_posix()
    if normalized != value:
        raise ComponentIntegrityError("component path is not canonical")
    return normalized


def _require_sha256(value: Any, name: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise ComponentIntegrityError(f"{name} must be canonical lowercase SHA-256")
    return value


def _verify_one_component(
    root: Path,
    expected: ComponentDigest,
    *,
    max_component_bytes: int,
) -> ComponentDigest:
    lexical = root.joinpath(*PurePosixPath(expected.path).parts)
    if _contains_symlink(root, lexical):
        raise ComponentIntegrityError(f"protected component is a symbolic link: {expected.path}")
    try:
        resolved = lexical.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ComponentIntegrityError(f"protected component is unavailable or escapes installation root: {expected.path}") from exc

    try:
        with resolved.open("rb") as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise ComponentIntegrityError(f"protected component is not a regular file: {expected.path}")
            if before.st_size > max_component_bytes:
                raise ComponentIntegrityError(f"protected component exceeds verification size bound: {expected.path}")
            digest = sha256()
            total = 0
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_component_bytes:
                    raise ComponentIntegrityError(f"protected component exceeds verification size bound: {expected.path}")
                digest.update(chunk)
            after = os.fstat(handle.fileno())
    except ComponentIntegrityError:
        raise
    except OSError as exc:
        raise ComponentIntegrityError(f"protected component cannot be read: {expected.path}") from exc

    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ComponentIntegrityError(f"protected component changed during verification: {expected.path}")
    actual = digest.hexdigest()
    if not hmac.compare_digest(actual, expected.sha256):
        raise ComponentIntegrityError(f"protected component integrity check failed: {expected.path}")
    return ComponentDigest(path=expected.path, sha256=actual, size=total)


def _contains_symlink(root: Path, target: Path) -> bool:
    try:
        relative = target.relative_to(root)
    except ValueError:
        return True
    current = root
    for part in relative.parts:
        current = current / part
        try:
            if current.is_symlink():
                return True
        except OSError:
            return True
    return False
