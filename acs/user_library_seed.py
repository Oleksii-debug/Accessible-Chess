from __future__ import annotations

"""Optional package-local private user Library seed.

The public product contains only this deterministic ingress seam. Private book
bytes are never committed to the repository. A user-specific release may place
strict UTF-8 PGN files beside the executable under
"release-content/user-library-seed" with a bounded manifest. Startup validates
every byte before publishing games through the canonical Library transaction.

No network, OCR, AI service or API key is involved.
"""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Mapping

from .library_import_service import LibraryImportService
from .pgn_roundtrip import parse_pgn_text


SCHEMA_VERSION = 1
BUNDLE_KIND = "accessible-chess-private-user-library-seed"
MANIFEST_NAME = "manifest.json"
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_SOURCE_COUNT = 64
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_WINDOWS_FORBIDDEN_FILENAME_CHARS = frozenset('<>"|?*')
_WINDOWS_DEVICE_SUFFIXES = tuple(str(index) for index in range(1, 10)) + ("¹", "²", "³")
_WINDOWS_RESERVED_BASENAMES = frozenset(
    {"con", "prn", "aux", "nul", "conin$", "conout$"}
    | {f"com{suffix}" for suffix in _WINDOWS_DEVICE_SUFFIXES}
    | {f"lpt{suffix}" for suffix in _WINDOWS_DEVICE_SUFFIXES}
)


class UserLibrarySeedError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class UserLibrarySeedEntry:
    file_name: str
    display_name: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class UserLibrarySeedManifest:
    root: Path
    entries: tuple[UserLibrarySeedEntry, ...]


@dataclass(frozen=True, slots=True)
class UserLibrarySeedSummary:
    source_count: int
    game_count: int
    reused_source_count: int

    def as_dict(self) -> dict[str, int | bool]:
        return {
            "available": True,
            "source_count": self.source_count,
            "game_count": self.game_count,
            "reused_source_count": self.reused_source_count,
            "network_required": False,
            "ai_required": False,
        }


def default_user_library_seed_root() -> Path:
    import sys
    return Path(sys.executable).resolve().parent / "release-content" / "user-library-seed"


def _is_reparse(st: os.stat_result) -> bool:
    attrs = getattr(st, "st_file_attributes", 0)
    marker = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attrs & marker)


def _regular_file(path: Path, *, label: str, maximum: int) -> os.stat_result:
    try:
        st = path.lstat()
    except OSError as exc:
        raise UserLibrarySeedError(f"{label} is unavailable") from exc
    if not stat.S_ISREG(st.st_mode) or stat.S_ISLNK(st.st_mode) or _is_reparse(st):
        raise UserLibrarySeedError(f"{label} must be a direct regular file")
    if st.st_size <= 0 or st.st_size > maximum:
        raise UserLibrarySeedError(f"{label} byte size is invalid")
    return st


def _same_file_identity(first: os.stat_result, second: os.stat_result) -> bool:
    try:
        return os.path.samestat(first, second)
    except (AttributeError, OSError):
        first_identity = (
            getattr(first, "st_dev", None),
            getattr(first, "st_ino", None),
        )
        second_identity = (
            getattr(second, "st_dev", None),
            getattr(second, "st_ino", None),
        )
        if None in first_identity or None in second_identity:
            return False
        return first_identity == second_identity


def _stable_change_metadata(st: os.stat_result) -> tuple[int, int] | None:
    """Return the portable change metadata required for a stable read proof.

    Identity plus size alone cannot detect an in-place same-length rewrite of
    an already-open file. Python exposes nanosecond mtime and ctime on the
    supported Windows/Linux runtimes; if either signal is unavailable, fail
    closed rather than silently weakening the private-seed ingress boundary.
    """

    mtime_ns = getattr(st, "st_mtime_ns", None)
    ctime_ns = getattr(st, "st_ctime_ns", None)
    if type(mtime_ns) is not int or type(ctime_ns) is not int:
        return None
    return mtime_ns, ctime_ns


def _same_file_snapshot(first: os.stat_result, second: os.stat_result) -> bool:
    if not _same_file_identity(first, second):
        return False
    if getattr(first, "st_size", None) != getattr(second, "st_size", None):
        return False
    first_change = _stable_change_metadata(first)
    second_change = _stable_change_metadata(second)
    return first_change is not None and first_change == second_change


def _read_stable_regular_file(
    path: Path,
    *,
    label: str,
    maximum: int,
    changed_message: str,
    expected_size: int | None = None,
) -> bytes:
    """Read one direct file while binding bytes to one stable file snapshot.

    Path-only before/after stats are insufficient: a same-size replacement can
    be installed just before open() and the original pathname restored later.
    Identity plus size is also insufficient because an already-open inode can
    be rewritten in place without changing either. Bind the opened descriptor
    to the pre-open pathname identity *and* nanosecond change metadata, keep the
    read bounded to the validated size, then prove descriptor and pathname
    snapshots remained unchanged throughout the read.
    """

    before = _regular_file(path, label=label, maximum=maximum)
    if expected_size is not None and before.st_size != expected_size:
        raise UserLibrarySeedError(f"{label} byte size mismatch")
    if _stable_change_metadata(before) is None:
        raise UserLibrarySeedError(changed_message)
    try:
        with path.open("rb") as handle:
            opened_before = os.fstat(handle.fileno())
            if (
                not stat.S_ISREG(opened_before.st_mode)
                or _is_reparse(opened_before)
                or not _same_file_snapshot(before, opened_before)
            ):
                raise UserLibrarySeedError(changed_message)
            payload = handle.read(before.st_size + 1)
            opened_after = os.fstat(handle.fileno())
    except UserLibrarySeedError:
        raise
    except OSError as exc:
        raise UserLibrarySeedError(f"{label} cannot be read") from exc

    after = _regular_file(path, label=label, maximum=maximum)
    if (
        len(payload) != before.st_size
        or not _same_file_snapshot(opened_before, opened_after)
        or not _same_file_snapshot(before, after)
    ):
        raise UserLibrarySeedError(changed_message)
    return payload


def _direct_directory(path: Path, *, label: str) -> None:
    try:
        st = path.lstat()
    except OSError as exc:
        raise UserLibrarySeedError(f"{label} is unavailable") from exc
    if not stat.S_ISDIR(st.st_mode) or stat.S_ISLNK(st.st_mode) or _is_reparse(st):
        raise UserLibrarySeedError(f"{label} must be direct")


def _unique_json(text: str) -> object:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise UserLibrarySeedError("user Library seed manifest has duplicate keys")
            result[key] = value
        return result
    try:
        return json.loads(text, object_pairs_hook=pairs)
    except UserLibrarySeedError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise UserLibrarySeedError("user Library seed manifest is invalid JSON") from exc


def _portable_name(value: object) -> str:
    if type(value) is not str:
        raise UserLibrarySeedError("user Library seed filename is invalid")
    name = value
    windows_basename = name.split(".", 1)[0].rstrip(" .").casefold()
    try:
        windows_utf16_units = len(name.encode("utf-16-le", errors="strict")) // 2
    except UnicodeEncodeError:
        windows_utf16_units = None
    if (
        not name
        or name != name.strip()
        or name.endswith(".")
        or len(name) > 255
        or windows_utf16_units is None
        or windows_utf16_units > 255
        or name in {".", ".."}
        or "/" in name
        or "\\" in name
        or ":" in name
        or any(character in _WINDOWS_FORBIDDEN_FILENAME_CHARS for character in name)
        or windows_basename in _WINDOWS_RESERVED_BASENAMES
        or any(ord(character) < 32 or ord(character) == 0x7F for character in name)
        or Path(name).name != name
        or not name.casefold().endswith(".pgn")
    ):
        raise UserLibrarySeedError("user Library seed filename is unsafe")
    return name


def _display_name(value: object) -> str:
    if type(value) is not str:
        raise UserLibrarySeedError("user Library seed display name is invalid")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        raise UserLibrarySeedError("user Library seed display name is invalid")
    if (
        not value
        or value != value.strip()
        or len(value) > 512
        or any(ord(character) < 32 or ord(character) == 0x7F for character in value)
    ):
        raise UserLibrarySeedError("user Library seed display name is invalid")
    return value


def load_user_library_seed(root: str | Path) -> UserLibrarySeedManifest:
    root = Path(root)
    # The runtime contract is package-local. Checking only the final seed
    # directory is insufficient because a junction/symlink at release-content
    # can redirect the otherwise-direct child outside the package tree.
    _direct_directory(root.parent, label="user Library seed parent directory")
    _direct_directory(root, label="user Library seed directory")
    manifest_path = root / MANIFEST_NAME
    manifest_bytes = _read_stable_regular_file(
        manifest_path,
        label="user Library seed manifest",
        maximum=MAX_MANIFEST_BYTES,
        changed_message="user Library seed manifest changed while reading",
    )
    try:
        manifest_text = manifest_bytes.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise UserLibrarySeedError("user Library seed manifest is not UTF-8") from exc
    raw = _unique_json(manifest_text)
    if not isinstance(raw, dict) or set(raw) != {
        "schema_version",
        "bundle_kind",
        "runtime_network_required",
        "ai_required",
        "files",
    }:
        raise UserLibrarySeedError("user Library seed manifest contract is invalid")
    if (
        type(raw["schema_version"]) is not int
        or raw["schema_version"] != SCHEMA_VERSION
        or raw["bundle_kind"] != BUNDLE_KIND
    ):
        raise UserLibrarySeedError("user Library seed manifest identity is invalid")
    if raw["runtime_network_required"] is not False or raw["ai_required"] is not False:
        raise UserLibrarySeedError("user Library seed must be fully local")
    files = raw["files"]
    if not isinstance(files, list) or not 1 <= len(files) <= MAX_SOURCE_COUNT:
        raise UserLibrarySeedError("user Library seed source count is invalid")

    entries: list[UserLibrarySeedEntry] = []
    names: set[str] = set()
    expected_inventory = {MANIFEST_NAME.casefold()}
    for item in files:
        if not isinstance(item, Mapping) or set(item) != {
            "file",
            "display_name",
            "bytes",
            "sha256",
        }:
            raise UserLibrarySeedError("user Library seed source metadata is invalid")
        name = _portable_name(item["file"])
        folded = name.casefold()
        if folded in names:
            raise UserLibrarySeedError("user Library seed contains duplicate filenames")
        names.add(folded)
        expected_inventory.add(folded)
        display = _display_name(item["display_name"])
        size = item["bytes"]
        digest = item["sha256"]
        if type(size) is not int or not 1 <= size <= MAX_SOURCE_BYTES:
            raise UserLibrarySeedError("user Library seed source byte size is invalid")
        if type(digest) is not str or _SHA256_RE.fullmatch(digest) is None:
            raise UserLibrarySeedError("user Library seed source SHA-256 is invalid")
        entries.append(UserLibrarySeedEntry(name, display, size, digest))

    try:
        children = tuple(root.iterdir())
    except OSError as exc:
        raise UserLibrarySeedError("user Library seed inventory cannot be read") from exc
    actual = {child.name.casefold() for child in children}
    if len(actual) != len(children) or actual != expected_inventory:
        raise UserLibrarySeedError("user Library seed inventory does not match manifest")
    return UserLibrarySeedManifest(root=root, entries=tuple(entries))


def _verified_source_bytes(manifest: UserLibrarySeedManifest, entry: UserLibrarySeedEntry) -> bytes:
    path = manifest.root / entry.file_name
    payload = _read_stable_regular_file(
        path,
        label="user Library seed PGN",
        maximum=MAX_SOURCE_BYTES,
        changed_message="user Library seed PGN changed while reading",
        expected_size=entry.size_bytes,
    )
    if hashlib.sha256(payload).hexdigest() != entry.sha256:
        raise UserLibrarySeedError("user Library seed PGN identity mismatch")
    return payload


def _validated_seed_games(manifest: UserLibrarySeedManifest, entry: UserLibrarySeedEntry):
    payload = _verified_source_bytes(manifest, entry)
    try:
        text = payload.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise UserLibrarySeedError("user Library seed PGN is not UTF-8") from exc
    try:
        games = parse_pgn_text(text, strict=True)
    except Exception as exc:
        raise UserLibrarySeedError("user Library seed PGN is not canonical") from exc
    if not games:
        raise UserLibrarySeedError("user Library seed PGN contains no games")
    return games


def _preflight_user_library_seed(manifest: UserLibrarySeedManifest) -> None:
    """Validate the complete static package before any ACSDB publication.

    Parsed GameTrees are deliberately discarded between sources so package
    validation remains bounded to one source at a time. Publication re-verifies
    and re-parses each source immediately before handing it to the canonical
    atomic per-source Library service.
    """

    for entry in manifest.entries:
        _validated_seed_games(manifest, entry)


def import_user_library_seed(database, manifest: UserLibrarySeedManifest) -> UserLibrarySeedSummary:
    _preflight_user_library_seed(manifest)
    importer = LibraryImportService(database)
    game_count = 0
    reused = 0
    for entry in manifest.entries:
        games = _validated_seed_games(manifest, entry)
        result = importer.import_games(
            games,
            source_name=entry.display_name,
            source_format="pgn",
            source_sha256=entry.sha256,
        )
        game_count += int(result.game_count)
        reused += 1 if result.reused else 0
    return UserLibrarySeedSummary(
        source_count=len(manifest.entries),
        game_count=game_count,
        reused_source_count=reused,
    )


__all__ = [
    "BUNDLE_KIND",
    "MANIFEST_NAME",
    "SCHEMA_VERSION",
    "UserLibrarySeedError",
    "UserLibrarySeedEntry",
    "UserLibrarySeedManifest",
    "UserLibrarySeedSummary",
    "default_user_library_seed_root",
    "import_user_library_seed",
    "load_user_library_seed",
]
