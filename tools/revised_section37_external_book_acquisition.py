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


def verify_original_book(record: dict, external_root: Path) -> dict:
    """Verify a precisely cataloged upstream TEST_ONLY book without copying it."""
    identity = record.get("id")
    if type(identity) is not str or not _ID.fullmatch(identity):
        raise LawfulCorpusError("book source id invalid")
    if (
        record.get("acquisition") != "PINNED_NOT_DOWNLOADED_IN_THIS_PASS"
        or record.get("format") != "txt"
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
    verified_local_source(path, record)
    # Path re-open is used only for exact, repeat identity; digest is checked
    # again on the bytes consumed here so a swap can never claim a false PASS.
    raw = path.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if (
        len(raw) != record["indexed_bytes"]
        or actual != record["sha256"]
        or _git_blob(raw) != expected_git
    ):
        raise LawfulCorpusError("external original-book identity changed")
    # Never include raw text, owner secrets or absolute filesystem paths in reports.
    return {
        "source_id": identity,
        "title": record.get("title"),
        "author": record.get("author"),
        "source_page": record.get("source_page"),
        "source_format": "txt",
        "sha256": actual,
        "git_blob": expected_git,
        "original_bytes": len(raw),
        "acquisition": "VERIFIED_EPHEMERAL_EXTERNAL",
        "redistribution": "NOT_CLEARED",
        "public_release": "EXCLUDED",
        "imported_to_library": False,
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
    result = {
        "kind": "revised-section37-ephemeral-upstream-book-source-provenance",
        "status": "PASS",
        "source_commit_sha": expected,
        "verified_original_book_count": len(verified),
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
        "verified_original_book_count": len(verified),
        "public_release_authorized": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
