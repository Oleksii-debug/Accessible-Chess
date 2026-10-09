"""Section 37 lawful external-book acquisition readback, never public packaging.

GitHub Actions checks out upstream GITenberg repositories into a disposable
directory. This *single source-verification boundary* reads original source
bytes and validates pinned SHA256, Git blob, exact size and provenance.
It does not fetch unpinned sources, trust a basename, invent format support,
or relicense Gutenberg material as CC0. Sources remain external/test-only.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess

from acs.lawful_corpus_registry import (
    LawfulCorpusError,
    load_catalog,
    verified_local_source,
)

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "revised-section37-original-books-readback.json"
_ID = re.compile(r"^[a-z0-9][a-z0-9_]{2,79}$")
_GIT_BLOB = re.compile(r"^[0-9a-f]{40}$")
_MAX_BOOKS = 32


def _direct_path(root: Path, relative: object) -> Path:
    """Refuse absolute paths, traversal, symlinks, Windows reparse points."""
    if type(relative) is not str or len(relative) > 192 or "\\" in relative or ":" in relative:
        raise LawfulCorpusError("external source relative path invalid")
    parts = relative.split("/")
    if len(parts) != 2 or any(not x or x in (".", "..") for x in parts):
        raise LawfulCorpusError("external source must belong to a dedicated checkout")
    if not root.is_dir() or root.is_symlink():
        raise LawfulCorpusError("external checkout root is not direct")
    current = root
    for name in parts:
        current = current / name
        try:
            info = current.lstat()
        except OSError as exc:
            raise LawfulCorpusError("external original file absent") from exc
        if (
            stat.S_ISLNK(info.st_mode)
            or getattr(info, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        ):
            raise LawfulCorpusError("external source cannot follow indirect path")
    if not stat.S_ISREG(info.st_mode):
        raise LawfulCorpusError("external source must be a regular file")
    return current


def _git_blob(raw: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\x00" + raw).hexdigest()


def _bounded_direct_snapshot(path: Path, limit: int) -> bytes:
    """Read a single verified regular-file identity with a strict memory cap."""
    if type(limit) is not int or not 0 < limit <= 128 * 1024 * 1024:
        raise LawfulCorpusError("original source snapshot limit invalid")
    try:
        before = path.lstat()
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            attrs = getattr(before, "st_file_attributes", 0)
            if (
                not stat.S_ISREG(before.st_mode)
                or stat.S_ISLNK(before.st_mode)
                or attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
                or not os.path.samestat(before, opened)
                or before.st_size <= 0 or before.st_size > limit
            ):
                raise LawfulCorpusError("original source changed while opening")
            raw = stream.read(limit + 1)
            opened_after = os.fstat(stream.fileno())
        after = path.lstat()
    except (OSError, ValueError) as exc:
        raise LawfulCorpusError("original source snapshot cannot be read") from exc
    if (
        not os.path.samestat(before, opened_after)
        or not os.path.samestat(before, after)
        or opened_after.st_size != before.st_size
        or len(raw) != before.st_size
        or not 0 < len(raw) <= limit
    ):
        raise LawfulCorpusError("original source changed during snapshot")
    return raw


def verify_original_book(record: dict, external_root: Path) -> dict:
    """Verify a precisely cataloged upstream TEST_ONLY book without copying it."""
    identity = record.get("id")
    if type(identity) is not str or not _ID.fullmatch(identity):
        raise LawfulCorpusError("book source id invalid")
    if (
        record.get("acquisition") != "PINNED_NOT_DOWNLOADED_IN_THIS_PASS"
        or record.get("format") not in ("txt", "md")
        or record.get("redistribution") != "NOT_CLEARED"
        or record.get("test_access") != "EXTERNAL_EPHEMERAL_ONLY"
        or record.get("public_release") != "EXCLUDED"
    ):
        raise LawfulCorpusError("source is not authorized for ephemeral original-book readback")
    expected_git = record.get("upstream_git_blob")
    if type(expected_git) is not str or not _GIT_BLOB.fullmatch(expected_git):
        raise LawfulCorpusError("source has no pinned original git blob")
    if type(record.get("indexed_bytes")) is not int:
        raise LawfulCorpusError("original source has no pinned exact byte count")
    path = _direct_path(external_root, record.get("external_checkout_path"))
    license_path = _direct_path(external_root, record.get("external_license_checkout_path"))
    verified_local_source(path, record)
    # A separate unbounded read_bytes() could consume swapped or growing
    # source data before its final SHA check. Check exact opened identity.
    raw = _bounded_direct_snapshot(path, record["max_bytes"])
    actual = hashlib.sha256(raw).hexdigest()
    if (
        len(raw) != record["indexed_bytes"]
        or actual != record["sha256"]
        or _git_blob(raw) != expected_git
    ):
        raise LawfulCorpusError("external original-book identity changed")
    # Original Project Gutenberg conditions travel separately from book bytes.
    # Test-only is not a substitute for license/source attribution.
    license_blob = record.get("external_license_git_blob")
    if type(license_blob) is not str or not _GIT_BLOB.fullmatch(license_blob):
        raise LawfulCorpusError("external license git blob is not pinned")
    license_size = record.get("external_license_indexed_bytes")
    if type(license_size) is not int or not 0 < license_size <= 1024 * 1024:
        raise LawfulCorpusError("external license size is not pinned")
    license_raw = _bounded_direct_snapshot(license_path, license_size)
    if (
        len(license_raw) != license_size
        or _git_blob(license_raw) != license_blob
        or hashlib.sha256(license_raw).hexdigest() != record.get("external_license_sha256")
        or not license_raw.lstrip().startswith(
            b"THE FULL PROJECT GUTENBERG LICENSE"
            if record["format"] == "txt"
            else b"GNU GENERAL PUBLIC LICENSE"
        )
    ):
        raise LawfulCorpusError("external source license bytes changed")
    rights_notice = None
    if record["format"] == "md":
        # The Markdown book itself declares CC BY-NC-SA, notwithstanding the
        # repository's generic GPL LICENSE. Both originals must be retained as
        # metadata-only evidence, and no release rights may be inferred.
        rights_blob = record.get("external_book_rights_notice_git_blob")
        if type(rights_blob) is not str or not _GIT_BLOB.fullmatch(rights_blob):
            raise LawfulCorpusError("book-specific rights notice is not pinned")
        rights_path = _direct_path(external_root, record.get("external_book_rights_notice_path"))
        rights_raw = _bounded_direct_snapshot(rights_path, 128 * 1024)
        if (
            _git_blob(rights_raw) != rights_blob
            or b"Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International" not in rights_raw
        ):
            raise LawfulCorpusError("original book-specific CC BY-NC-SA rights notice changed")
        rights_notice = {
            "git_blob": rights_blob,
            "sha256": hashlib.sha256(rights_raw).hexdigest(),
            "bytes": len(rights_raw),
            "source_declared_book_license": "CC-BY-NC-SA-4.0",
            "public_release": "EXCLUDED",
        }
    # Never include raw text, owner secrets or absolute filesystem paths in reports.
    return {
        "source_id": identity,
        "title": record.get("title"),
        "author": record.get("author"),
        "source_page": record.get("source_page"),
        "source_format": record["format"],
        "sha256": actual,
        "git_blob": expected_git,
        "license_git_blob": license_blob,
        "license_sha256": hashlib.sha256(license_raw).hexdigest(),
        "license_bytes": len(license_raw),
        "book_rights_notice": rights_notice,
        "original_bytes": len(raw),
        "acquisition": "VERIFIED_EPHEMERAL_EXTERNAL",
        "redistribution": "NOT_CLEARED",
        "public_release": "EXCLUDED",
        "imported_to_library": False,
        "original_bytes_packaged": False,
    }


def verify_original_cc0_pdf(record: dict, external_root: Path) -> dict:
    """Read a genuine upstream PDF as bytes only; no PDF parsing or release."""
    if (
        record.get("id") != "cc0_capablanca_open_pdf_original_source"
        or record.get("format") != "pdf"
        or record.get("acquisition") != "DISCOVERED_NOT_HASH_VERIFIED"
        or record.get("sha256") is not None
        or record.get("test_access") != "EXTERNAL_CC0_PDF_SOURCE_ONLY"
        or record.get("public_release") != "EXCLUDED_PENDING_QUALIFICATION"
        or not str(record.get("license", "")).startswith("CC0-1.0")
        or not str(record.get("redistribution", "")).startswith("permitted under source CC0")
    ):
        raise LawfulCorpusError("external original PDF source is not authorized")
    original_blob = record.get("upstream_git_blob")
    license_blob = record.get("external_license_git_blob")
    if (
        type(original_blob) is not str or not _GIT_BLOB.fullmatch(original_blob)
        or type(license_blob) is not str or not _GIT_BLOB.fullmatch(license_blob)
    ):
        raise LawfulCorpusError("original CC0 PDF source/license Git identity is missing")
    path = _direct_path(external_root, record.get("external_checkout_path"))
    license_path = _direct_path(external_root, record.get("external_license_checkout_path"))
    original = _bounded_direct_snapshot(path, record.get("max_bytes"))
    license_data = _bounded_direct_snapshot(license_path, 1024 * 1024)
    if (
        _git_blob(original) != original_blob
        or not original.startswith(b"%PDF-")
        or b"%%EOF" not in original[-2048:]
        or _git_blob(license_data) != license_blob
        or not license_data.startswith(b"Creative Commons Legal Code")
        or b"CC0 1.0 Universal" not in license_data[:512]
    ):
        raise LawfulCorpusError("original CC0 PDF or its license differs from trusted source")
    return {
        "source_id": record["id"],
        "title": record.get("title"),
        "author": record.get("author"),
        "source_page": record.get("source_page"),
        "source_format": "pdf",
        "sha256": hashlib.sha256(original).hexdigest(),
        "git_blob": original_blob,
        "original_bytes": len(original),
        "license_git_blob": license_blob,
        "license_sha256": hashlib.sha256(license_data).hexdigest(),
        "license_bytes": len(license_data),
        "acquisition": "VERIFIED_EPHEMERAL_EXTERNAL_GIT_BLOB",
        "expected_source_sha256_pre_qualified": False,
        "public_release": "EXCLUDED_PENDING_QUALIFICATION",
        "semantic_pdf_import": "NOT_TESTED_BY_SOURCE_ACQUISITION",
        "original_bytes_packaged": False,
    }


def verify_external_books(records: tuple[dict, ...], external_root: Path) -> tuple[dict, ...]:
    selected = [item for item in records if "external_checkout_path" in item]
    if not selected or len(selected) > _MAX_BOOKS:
        raise LawfulCorpusError("external book source batch is missing or too large")
    seen: set[str] = set()
    results: list[dict] = []
    for entry in selected:
        if entry["id"] in seen:
            raise LawfulCorpusError("external source identity duplicated")
        seen.add(entry["id"])
        if entry.get("format") == "pdf":
            results.append(verify_original_cc0_pdf(entry, external_root))
        else:
            results.append(verify_original_book(entry, external_root))
    return tuple(sorted(results, key=lambda item: item["source_id"]))


def _exact_head() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"],
            cwd=ROOT, capture_output=True, text=True, check=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise LawfulCorpusError("exact checkout source identity unavailable") from exc
    head = result.stdout.strip()
    expected = os.environ.get("ACCESSIBLE_CHESS_EXPECTED_HEAD")
    if not _GIT_BLOB.fullmatch(head) or expected is None or head != expected:
        raise LawfulCorpusError("source candidate SHA does not match workflow HEAD")
    return head


def main() -> None:
    # Stale success reports are deleted before *any* network/external read.
    REPORT.unlink(missing_ok=True)
    temporary = REPORT.with_suffix(".tmp")
    temporary.unlink(missing_ok=True)
    expected = _exact_head()
    external = os.environ.get("ACS_37_GITENBERG_ROOT")
    if not external:
        raise LawfulCorpusError("dedicated external book checkout root missing")
    verified = verify_external_books(load_catalog(), Path(external))
    formats = {record["source_format"] for record in verified}
    if formats != {"txt", "md", "pdf"}:
        raise LawfulCorpusError("required real original TXT, Markdown and PDF families missing")
    book_count = sum(1 for record in verified if record["source_format"] in ("txt", "md"))
    result = {
        "kind": "revised-section37-ephemeral-upstream-book-source-provenance",
        "status": "PASS",
        "source_commit_sha": expected,
        "verified_original_book_count": book_count,
        "verified_original_pdf_count": sum(1 for item in verified if item["source_format"] == "pdf"),
        "sources": verified,
        "public_release_authorized": False,
        "all_six_section37_requirements_done": False,
    }
    try:
        temporary.write_text(
            json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, REPORT)
    finally:
        temporary.unlink(missing_ok=True)
    print(json.dumps({
        "source_commit_sha": expected,
        "verified_original_book_count": book_count,
        "verified_original_pdf_count": sum(1 for item in verified if item["source_format"] == "pdf"),
        "public_release_authorized": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
