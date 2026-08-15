from __future__ import annotations

"""Fail-closed verification for the final ZIP release artifact.

The distribution directory is validated before compression by release_manifest.
This module validates the actual ZIP bytes that will be uploaded, so packaging
cannot silently omit, alter, duplicate, or inject payload files after that gate.
"""

import hashlib
from pathlib import PurePosixPath
import stat
from typing import Iterable
from zipfile import ZipFile, BadZipFile, ZipInfo

from .release_manifest import (
    DEFAULT_PRODUCT_NAME,
    ReleaseManifest,
    ReleaseFile,
)

_DEFAULT_ALLOWED_METADATA = frozenset({"RELEASE-MANIFEST.json", "RELEASE-BUILD.txt"})


def _safe_member_name(name: str) -> str:
    if not name or "\\" in name or "\x00" in name:
        raise ValueError(f"unsafe release archive path: {name!r}")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ValueError(f"unsafe release archive path: {name!r}")
    if path.as_posix() != name or any(":" in part for part in path.parts):
        raise ValueError(f"unsafe release archive path: {name!r}")
    return name


def _is_symlink(info: ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return stat.S_IFMT(mode) == stat.S_IFLNK


def _sha256_member(archive: ZipFile, info: ZipInfo, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with archive.open(info, "r") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def verify_release_archive(
    archive_path: str,
    manifest: ReleaseManifest,
    *,
    expected_product: str = DEFAULT_PRODUCT_NAME,
    expected_version: str | None = None,
    allowed_metadata: Iterable[str] = _DEFAULT_ALLOWED_METADATA,
) -> tuple[str, ...]:
    """Verify the exact ZIP artifact against the already-built release manifest."""

    defects: list[str] = []
    if manifest.product != expected_product:
        defects.append(
            f"release product mismatch: manifest={manifest.product!r}, expected={expected_product!r}"
        )
    if expected_version is not None and manifest.version != str(expected_version).strip():
        defects.append(
            f"release version mismatch: manifest={manifest.version!r}, expected={str(expected_version).strip()!r}"
        )

    try:
        allowed = {_safe_member_name(value).casefold() for value in allowed_metadata}
    except ValueError as exc:
        return tuple([*defects, str(exc)])

    listed: dict[str, ReleaseFile] = {item.path.casefold(): item for item in manifest.files}

    try:
        with ZipFile(archive_path, "r") as archive:
            infos: dict[str, ZipInfo] = {}
            for info in archive.infolist():
                if info.is_dir():
                    continue
                try:
                    name = _safe_member_name(info.filename)
                except ValueError as exc:
                    defects.append(str(exc))
                    continue
                if _is_symlink(info):
                    defects.append(f"release archive contains symlink: {name}")
                    continue
                folded = name.casefold()
                if folded in infos:
                    defects.append(f"duplicate case-insensitive archive path: {name}")
                    continue
                infos[folded] = info

            for folded, item in listed.items():
                info = infos.get(folded)
                if info is None:
                    defects.append(f"manifest file missing from archive: {item.path}")
                    continue
                if info.file_size != item.size:
                    defects.append(
                        f"archive size mismatch for {item.path}: expected {item.size}, found {info.file_size}"
                    )
                    continue
                if _sha256_member(archive, info) != item.sha256:
                    defects.append(f"archive SHA-256 mismatch for {item.path}")

            unexpected = sorted(
                info.filename
                for folded, info in infos.items()
                if folded not in listed and folded not in allowed
            )
            for name in unexpected:
                defects.append(f"unexpected unmanifested archive file: {name}")

            manifest_info = infos.get("release-manifest.json")
            if manifest_info is None:
                defects.append("release archive is missing RELEASE-MANIFEST.json")
            else:
                try:
                    embedded = ReleaseManifest.from_json(
                        archive.read(manifest_info).decode("utf-8-sig")
                    )
                except (UnicodeDecodeError, ValueError) as exc:
                    defects.append(f"embedded release manifest is invalid: {exc}")
                else:
                    if embedded != manifest:
                        defects.append("embedded release manifest does not match verified manifest")

    except (FileNotFoundError, IsADirectoryError, BadZipFile, OSError) as exc:
        defects.append(f"release archive cannot be opened: {exc}")

    return tuple(defects)
