from __future__ import annotations

"""Materialize an explicitly authorized private Library seed ZIP.

Private owner PGN bytes remain external to GitHub. This build-only ingress takes
an exact SHA-256-bound ZIP containing the canonical seed manifest and PGNs at
archive root, extracts it through a bounded path-safe reader, then delegates all
semantic validation to ``acs.user_library_seed`` and the canonical Library
import service. It does not implement PGN or chess semantics.
"""

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import zipfile

from acs.acsdb import AcsDatabase
from acs.version2_package_assembler import (
    Version2PackageAssemblyError,
    _publish_directory_no_replace,
)
from acs.user_library_seed import (
    MANIFEST_NAME,
    MAX_MANIFEST_BYTES,
    MAX_SOURCE_BYTES,
    MAX_SOURCE_COUNT,
    UserLibrarySeedError,
    import_user_library_seed,
    load_user_library_seed,
)


MAX_ARCHIVE_BYTES = MAX_MANIFEST_BYTES + MAX_SOURCE_COUNT * MAX_SOURCE_BYTES
MAX_ARCHIVE_MEMBERS = MAX_SOURCE_COUNT + 1
_COPY_CHUNK = 1024 * 1024
_WINDOWS_RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
    "com¹",
    "com²",
    "com³",
    "lpt¹",
    "lpt²",
    "lpt³",
}


class OwnerLibrarySeedMaterializeError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class OwnerLibrarySeedMaterializeReport:
    destination: Path
    archive_sha256: str
    archive_bytes: int
    source_count: int
    game_count: int

    def as_dict(self) -> dict[str, object]:
        return {
            "destination": str(self.destination),
            "archive_sha256": self.archive_sha256,
            "archive_bytes": self.archive_bytes,
            "source_count": self.source_count,
            "game_count": self.game_count,
            "result": "PASS",
        }


def _fail(message: str) -> None:
    raise OwnerLibrarySeedMaterializeError(message)


def _sha256_value(value: object) -> str:
    if type(value) is not str:
        _fail("owner Library seed archive SHA-256 is invalid")
    normalized = value.strip().casefold()
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
        _fail("owner Library seed archive SHA-256 is invalid")
    return normalized


def _direct_regular(path: Path, *, label: str) -> os.stat_result:
    try:
        info = path.lstat()
    except OSError as exc:
        raise OwnerLibrarySeedMaterializeError(f"{label} is unavailable") from exc
    attrs = getattr(info, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or bool(attrs & reparse)
    ):
        _fail(f"{label} must be a direct regular file")
    return info


def _snapshot_archive(source: Path, target: Path) -> tuple[str, int]:
    before = _direct_regular(source, label="owner Library seed ZIP")
    if before.st_size <= 0 or before.st_size > MAX_ARCHIVE_BYTES:
        _fail("owner Library seed ZIP byte size is invalid")
    digest = hashlib.sha256()
    copied = 0
    try:
        with source.open("rb") as reader, target.open("xb") as writer:
            opened = os.fstat(reader.fileno())
            if not os.path.samestat(before, opened) or opened.st_size != before.st_size:
                _fail("owner Library seed ZIP changed while being opened")
            while True:
                block = reader.read(_COPY_CHUNK)
                if not block:
                    break
                copied += len(block)
                if copied > MAX_ARCHIVE_BYTES:
                    _fail("owner Library seed ZIP exceeds the byte limit")
                digest.update(block)
                writer.write(block)
            opened_after = os.fstat(reader.fileno())
    except OwnerLibrarySeedMaterializeError:
        raise
    except OSError as exc:
        raise OwnerLibrarySeedMaterializeError(
            "owner Library seed ZIP could not be snapshotted"
        ) from exc
    after = _direct_regular(source, label="owner Library seed ZIP")
    if (
        copied != before.st_size
        or opened_after.st_size != before.st_size
        or after.st_size != before.st_size
        or not os.path.samestat(opened, opened_after)
        or not os.path.samestat(before, after)
    ):
        _fail("owner Library seed ZIP changed while being read")
    return digest.hexdigest(), copied


def _member_name(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        _fail("owner Library seed ZIP member path is unsafe")
    pure = PurePosixPath(value)
    if (
        pure.is_absolute()
        or len(pure.parts) != 1
        or pure.name != value
        or value in {".", ".."}
        or ":" in value
        or value.rstrip(" .") != value
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
        or value.split(".", 1)[0].casefold() in _WINDOWS_RESERVED_NAMES
    ):
        _fail("owner Library seed ZIP member path is unsafe")
    folded = value.casefold()
    if folded != MANIFEST_NAME.casefold() and not folded.endswith(".pgn"):
        _fail("owner Library seed ZIP may contain only manifest.json and PGN files")
    return value


def _extract_snapshot(snapshot: Path, destination: Path) -> None:
    try:
        archive = zipfile.ZipFile(snapshot, "r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise OwnerLibrarySeedMaterializeError(
            "owner Library seed ZIP is invalid"
        ) from exc
    with archive:
        members = archive.infolist()
        if not 2 <= len(members) <= MAX_ARCHIVE_MEMBERS:
            _fail("owner Library seed ZIP member count is invalid")
        seen: set[str] = set()
        total = 0
        for info in members:
            if info.is_dir():
                _fail("owner Library seed ZIP must contain root files only")
            if info.flag_bits & 0x1:
                _fail("owner Library seed ZIP cannot contain encrypted members")
            unix_type = (info.external_attr >> 16) & 0o170000
            if unix_type not in {0, 0o100000}:
                _fail("owner Library seed ZIP cannot contain links or special files")
            name = _member_name(info.filename)
            folded = name.casefold()
            if folded in seen:
                _fail("owner Library seed ZIP contains duplicate filenames")
            seen.add(folded)
            maximum = MAX_MANIFEST_BYTES if folded == MANIFEST_NAME.casefold() else MAX_SOURCE_BYTES
            if info.file_size <= 0 or info.file_size > maximum:
                _fail("owner Library seed ZIP member byte size is invalid")
            total += int(info.file_size)
            if total > MAX_ARCHIVE_BYTES:
                _fail("owner Library seed ZIP expands beyond the byte limit")

            target = destination / name
            try:
                with archive.open(info, "r") as reader, target.open("xb") as writer:
                    copied = 0
                    while True:
                        block = reader.read(_COPY_CHUNK)
                        if not block:
                            break
                        copied += len(block)
                        if copied > maximum:
                            _fail("owner Library seed ZIP member exceeds its byte limit")
                        writer.write(block)
                if copied != info.file_size:
                    _fail("owner Library seed ZIP member size changed during extraction")
            except OwnerLibrarySeedMaterializeError:
                raise
            except OSError as exc:
                raise OwnerLibrarySeedMaterializeError(
                    "owner Library seed ZIP member could not be extracted"
                ) from exc

        if MANIFEST_NAME.casefold() not in seen:
            _fail("owner Library seed ZIP manifest is missing")


def _qualify_seed(
    root: Path,
    *,
    expected_source_count: int,
    expected_game_count: int,
) -> tuple[int, int]:
    if type(expected_source_count) is not int or not 1 <= expected_source_count <= MAX_SOURCE_COUNT:
        _fail("expected owner Library seed source count is invalid")
    if type(expected_game_count) is not int or expected_game_count <= 0:
        _fail("expected owner Library seed game count is invalid")
    try:
        manifest = load_user_library_seed(root)
        with AcsDatabase(":memory:") as database:
            summary = import_user_library_seed(database, manifest)
    except UserLibrarySeedError as exc:
        raise OwnerLibrarySeedMaterializeError(
            "owner Library seed failed canonical validation/import"
        ) from exc
    except Exception as exc:
        raise OwnerLibrarySeedMaterializeError(
            "owner Library seed qualification failed unexpectedly"
        ) from exc
    if summary.source_count != expected_source_count:
        _fail(
            "owner Library seed source count mismatch: "
            f"actual={summary.source_count} expected={expected_source_count}"
        )
    if summary.game_count != expected_game_count:
        _fail(
            "owner Library seed game count mismatch: "
            f"actual={summary.game_count} expected={expected_game_count}"
        )
    if summary.reused_source_count != 0:
        _fail("owner Library seed qualification unexpectedly reused sources")
    return summary.source_count, summary.game_count


def materialize_owner_library_seed(
    source_zip: str | Path,
    destination: str | Path,
    *,
    expected_archive_sha256: str,
    expected_source_count: int = 6,
    expected_game_count: int = 3738,
) -> OwnerLibrarySeedMaterializeReport:
    source = Path(source_zip)
    output = Path(destination)
    wanted = _sha256_value(expected_archive_sha256)
    if output.exists() or output.is_symlink():
        _fail("owner Library seed destination must not already exist")
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise OwnerLibrarySeedMaterializeError(
            "owner Library seed destination parent cannot be prepared"
        ) from exc

    with tempfile.TemporaryDirectory(
        prefix=f".{output.name}.seed-ingress-",
        dir=output.parent,
    ) as temporary_raw:
        temporary = Path(temporary_raw)
        snapshot = temporary / "owner-seed.zip"
        digest, archive_bytes = _snapshot_archive(source, snapshot)
        if digest != wanted:
            _fail(
                "owner Library seed ZIP SHA-256 mismatch: "
                f"actual={digest} expected={wanted}"
            )
        extracted = temporary / "seed"
        extracted.mkdir()
        _extract_snapshot(snapshot, extracted)
        source_count, game_count = _qualify_seed(
            extracted,
            expected_source_count=expected_source_count,
            expected_game_count=expected_game_count,
        )
        try:
            _publish_directory_no_replace(extracted, output)
        except Version2PackageAssemblyError as exc:
            raise OwnerLibrarySeedMaterializeError(
                "owner Library seed could not be published atomically without replacement"
            ) from exc

    return OwnerLibrarySeedMaterializeReport(
        destination=output,
        archive_sha256=digest,
        archive_bytes=archive_bytes,
        source_count=source_count,
        game_count=game_count,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Safely materialize the exact private owner Library seed ZIP",
    )
    parser.add_argument("source_zip", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--expected-archive-sha256", required=True)
    parser.add_argument("--expected-source-count", type=int, default=6)
    parser.add_argument("--expected-game-count", type=int, default=3738)
    args = parser.parse_args()
    report = materialize_owner_library_seed(
        args.source_zip,
        args.destination,
        expected_archive_sha256=args.expected_archive_sha256,
        expected_source_count=args.expected_source_count,
        expected_game_count=args.expected_game_count,
    )
    print(json.dumps(report.as_dict(), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
