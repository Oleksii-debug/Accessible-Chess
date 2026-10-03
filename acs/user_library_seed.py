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


def _direct_directory(path: Path) -> None:
    try:
        st = path.lstat()
    except OSError as exc:
        raise UserLibrarySeedError("user Library seed directory is unavailable") from exc
    if not stat.S_ISDIR(st.st_mode) or stat.S_ISLNK(st.st_mode) or _is_reparse(st):
        raise UserLibrarySeedError("user Library seed directory must be direct")


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
    name = value.strip()
    if (
        not name
        or len(name) > 255
        or name in {".", ".."}
        or "/" in name
        or "\\" in name
        or ":" in name
        or Path(name).name != name
        or not name.casefold().endswith(".pgn")
    ):
        raise UserLibrarySeedError("user Library seed filename is unsafe")
    return name


def load_user_library_seed(root: str | Path) -> UserLibrarySeedManifest:
    root = Path(root)
    _direct_directory(root)
    manifest_path = root / MANIFEST_NAME
    manifest_stat = _regular_file(
        manifest_path,
        label="user Library seed manifest",
        maximum=MAX_MANIFEST_BYTES,
    )
    try:
        manifest_bytes = manifest_path.read_bytes()
    except OSError as exc:
        raise UserLibrarySeedError("user Library seed manifest cannot be read") from exc
    if len(manifest_bytes) != manifest_stat.st_size:
        raise UserLibrarySeedError("user Library seed manifest changed while reading")
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
    if raw["schema_version"] != SCHEMA_VERSION or raw["bundle_kind"] != BUNDLE_KIND:
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
        display = item["display_name"]
        if type(display) is not str or not display.strip() or len(display) > 512:
            raise UserLibrarySeedError("user Library seed display name is invalid")
        size = item["bytes"]
        digest = item["sha256"]
        if type(size) is not int or not 1 <= size <= MAX_SOURCE_BYTES:
            raise UserLibrarySeedError("user Library seed source byte size is invalid")
        if type(digest) is not str or _SHA256_RE.fullmatch(digest) is None:
            raise UserLibrarySeedError("user Library seed source SHA-256 is invalid")
        entries.append(UserLibrarySeedEntry(name, display.strip(), size, digest))

    try:
        children = tuple(root.iterdir())
    except OSError as exc:
        raise UserLibrarySeedError("user Library seed inventory cannot be read") from exc
    actual = {child.name.casefold() for child in children}
    if actual != expected_inventory:
        raise UserLibrarySeedError("user Library seed inventory does not match manifest")
    return UserLibrarySeedManifest(root=root, entries=tuple(entries))


def _verified_source_bytes(manifest: UserLibrarySeedManifest, entry: UserLibrarySeedEntry) -> bytes:
    path = manifest.root / entry.file_name
    before = _regular_file(path, label="user Library seed PGN", maximum=MAX_SOURCE_BYTES)
    if before.st_size != entry.size_bytes:
        raise UserLibrarySeedError("user Library seed PGN byte size mismatch")
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise UserLibrarySeedError("user Library seed PGN cannot be read") from exc
    after = _regular_file(path, label="user Library seed PGN", maximum=MAX_SOURCE_BYTES)
    if (
        after.st_size != before.st_size
        or getattr(after, "st_ino", None) != getattr(before, "st_ino", None)
        or getattr(after, "st_dev", None) != getattr(before, "st_dev", None)
    ):
        raise UserLibrarySeedError("user Library seed PGN changed while reading")
    if len(payload) != entry.size_bytes or hashlib.sha256(payload).hexdigest() != entry.sha256:
        raise UserLibrarySeedError("user Library seed PGN identity mismatch")
    return payload


def import_user_library_seed(database, manifest: UserLibrarySeedManifest) -> UserLibrarySeedSummary:
    importer = LibraryImportService(database)
    game_count = 0
    reused = 0
    for entry in manifest.entries:
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
