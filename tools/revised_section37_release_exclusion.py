"""Fail-closed public ZIP guard for unlicensed original corpus material.

Checks actual archive member bytes against the canonical source registry.
Only a verification tool, not a publication/permission or packaging decision.
Release pipelines must invoke audit_public_archive on the exact archive before
publishing; merely authoring this file is NOT such evidence.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import zipfile

from acs.lawful_corpus_registry import LawfulCorpusError, load_catalog

_ID = re.compile(r"^[a-z0-9][a-z0-9_]{2,79}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_CHUNK = 256 * 1024
_MAX_FILES = 50_000
_MAX_SINGLE_UNPACKED = 1024 * 1024 * 1024
_MAX_TOTAL_UNPACKED = 4 * 1024 * 1024 * 1024
_MAX_COMPRESS_RATIO = 600


def excluded_public_source_index(records: tuple[dict, ...]) -> dict:
    """Derive denied source digests and names, never authorize other content."""
    bad_hashes: dict[str, str] = {}
    bad_names: dict[str, str] = {}
    for entry in records:
        if type(entry) is not dict or not _ID.fullmatch(str(entry.get("id", ""))):
            raise LawfulCorpusError("invalid corpus registry when checking release")
        identity = entry["id"]
        exclusion = entry.get("public_release", "")
        if exclusion not in ("EXCLUDED", "EXCLUDED_PENDING_QUALIFICATION"):
            continue
        direct = entry.get("external_checkout_path") or entry.get("local_source")
        if type(direct) is str:
            p = PurePosixPath(direct)
            if p.name and p.name != ".":
                bad_names[p.name.casefold()] = identity
        digest = entry.get("sha256")
        if digest is not None:
            if type(digest) is not str or not _SHA.fullmatch(digest):
                raise LawfulCorpusError("invalid excluded original source SHA256")
            bad_hashes[digest] = identity
        companions = entry.get("external_companion_source_checksums", {})
        if type(companions) is not dict:
            raise LawfulCorpusError("invalid original ChessBase companion index")
        for name, item in companions.items():
            if type(name) is not str or "/" in name or "\\" in name or not name:
                raise LawfulCorpusError("unsafe original ChessBase companion basename")
            if type(item) is not dict or type(item.get("sha256")) is not str or not _SHA.fullmatch(item["sha256"]):
                raise LawfulCorpusError("invalid original ChessBase source SHA256")
            bad_hashes[item["sha256"]] = identity
            bad_names[name.casefold()] = identity
        oracle = entry.get("external_oracle_source_checksum")
        if oracle is not None:
            if (
                type(oracle) is not dict
                or type(oracle.get("name")) is not str
                or "/" in oracle["name"] or "\\" in oracle["name"]
                or type(oracle.get("sha256")) is not str
                or not _SHA.fullmatch(oracle["sha256"])
            ):
                raise LawfulCorpusError("invalid original PGN oracle release exclusion")
            bad_hashes[oracle["sha256"]] = identity
            bad_names[oracle["name"].casefold()] = identity
    if not bad_hashes or not bad_names:
        raise LawfulCorpusError("release-exclusion manifest unexpectedly empty")
    return {"sha256": bad_hashes, "basenames": bad_names}


def audit_public_archive(path: Path, records: tuple[dict, ...] | None = None) -> dict:
    """Refuse archive traversal, original corpora, content renames and zip bombs."""
    source_index = excluded_public_source_index(load_catalog() if records is None else records)
    hashes = source_index["sha256"]
    names = source_index["basenames"]
    try:
        before = path.lstat()
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_ISLNK(before.st_mode)
            or before.st_size <= 0
        ):
            raise LawfulCorpusError("public archive must be an existing direct file")
        with zipfile.ZipFile(path) as zf:
            members = zf.infolist()
            if not members or len(members) > _MAX_FILES:
                raise LawfulCorpusError("public release ZIP member count invalid")
            total_expected = 0
            seen_paths: set[str] = set()
            for info in members:
                rawname = info.filename
                normalized = rawname.replace("\\", "/")
                path_parts = PurePosixPath(normalized).parts
                if (
                    normalized.startswith("/")
                    or re.match(r"^[A-Za-z]:", normalized)
                    or not path_parts
                    or any(part in ("..", ".") for part in path_parts)
                ):
                    raise LawfulCorpusError("release archive contains unsafe member path")
                folded = normalized.casefold().rstrip("/")
                if folded in seen_paths:
                    raise LawfulCorpusError("release archive repeats a member path")
                seen_paths.add(folded)
                if (info.external_attr >> 16) & 0o170000 == stat.S_IFLNK:
                    raise LawfulCorpusError("release archive contains symlink")
                if info.is_dir():
                    continue
                if (
                    info.file_size < 0
                    or info.file_size > _MAX_SINGLE_UNPACKED
                    or info.compress_size <= 0
                    or info.file_size > _MAX_COMPRESS_RATIO * info.compress_size
                ):
                    raise LawfulCorpusError("release archive contains oversized/compression-bomb member")
                total_expected += info.file_size
                if total_expected > _MAX_TOTAL_UNPACKED:
                    raise LawfulCorpusError("release archive decompressed size over budget")
                owner = names.get(PurePosixPath(normalized).name.casefold())
                if owner:
                    raise LawfulCorpusError("public release contains excluded original source filename: " + owner)
                with zf.open(info) as stream:
                    hasher = hashlib.sha256()
                    total = 0
                    while chunk := stream.read(_CHUNK):
                        total += len(chunk)
                        if total > info.file_size or total > _MAX_SINGLE_UNPACKED:
                            raise LawfulCorpusError("release member exceeded stated size")
                        hasher.update(chunk)
                if total != info.file_size:
                    raise LawfulCorpusError("release archive member bytes disagree with ZIP manifest")
                owner = hashes.get(hasher.hexdigest())
                if owner:
                    raise LawfulCorpusError("public release contains byte-identical excluded original source: " + owner)
        after = path.lstat()
        if not os.path.samestat(before, after) or before.st_size != after.st_size:
            raise LawfulCorpusError("release archive changed while auditing")
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile, RuntimeError, ValueError) as exc:
        if isinstance(exc, LawfulCorpusError):
            raise
        raise LawfulCorpusError("public release ZIP unreadable or invalid") from exc
    return {
        "public_archive_path": path.name,
        "source_registry_entry_count": len(load_catalog() if records is None else records),
        "archive_member_count": len(members),
        "audited_excluded_original_sha256_count": len(hashes),
        "audited_excluded_original_filename_count": len(names),
        "result": "PASS_ONLY_FOR_TESTED_ZIP_BYTES",
        "public_distribution_rights_granted": False,
    }


def main() -> None:
    archive_name = os.environ.get("ACS_37_PUBLIC_RELEASE_ZIP")
    if not archive_name:
        raise LawfulCorpusError("set ACS_37_PUBLIC_RELEASE_ZIP to exact finished release ZIP")
    outcome = audit_public_archive(Path(archive_name))
    print(json.dumps(outcome, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
