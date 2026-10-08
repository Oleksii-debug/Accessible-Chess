"""Revised Section 37: original, complete GPL libcbh CBH source-family byte receipt.

The canonical chess/ChessBase format adapter remains elsewhere. This module
is source acquisition and immutable provenance only. It never decodes a CBH,
claims CBF/CBV/2CBH/CBONE, or redistributes proprietary/GPL test bytes.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess

from acs.lawful_corpus_registry import LawfulCorpusError, load_catalog

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "revised-section37-original-cbh-companion-evidence.json"
UPSTREAM_COMMIT = "9641c5c3949d8fb210b17dd9aa54455645843696"
SHA40 = re.compile(r"^[a-f0-9]{40}$")
SAFE = re.compile(r"^[A-Za-z0-9_+.-]{1,96}$")
SUFFIXES = frozenset({".cbh", ".cbg", ".cbp", ".cbt", ".cba", ".cbs"})
MAX_FILE = 32 * 1024 * 1024
MAX_FAMILY = 64 * 1024 * 1024


def _raw_git_blob(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\x00" + data).hexdigest()


def _regular_source(path: Path, *, max_bytes: int = MAX_FILE) -> bytes:
    """Read only direct, bounded original files, validating path/file identity."""
    current = path
    # The original fixture directory and the file are both untrusted inputs.
    for part in (path.parent, current):
        try:
            info = part.lstat()
        except OSError as exc:
            raise LawfulCorpusError("original CBH fixture missing") from exc
        if stat.S_ISLNK(info.st_mode) or (
            getattr(info, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        ):
            raise LawfulCorpusError("indirect CBH corpus path rejected")
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= max_bytes:
            raise LawfulCorpusError("original CBH file is empty, special or over budget")
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if not os.path.samestat(before, opened):
                raise LawfulCorpusError("original CBH file replaced while opening")
            raw = stream.read(max_bytes + 1)
            at_end = stream.read(1)
            after_open = os.fstat(stream.fileno())
        after = path.lstat()
    except OSError as exc:
        raise LawfulCorpusError("original CBH file cannot be read") from exc
    if (
        not raw or len(raw) > max_bytes or at_end
        or len(raw) != before.st_size
        or not os.path.samestat(before, after_open)
        or not os.path.samestat(before, after)
    ):
        raise LawfulCorpusError("original CBH file changed during bounded read")
    return raw


def verify_gpl_cbh_family(record: dict, checkout: Path) -> dict:
    """Fail closed on any absent/replaced/extra companion, oracle or GPL license."""
    if (
        record.get("format") != "cbh (multifile original companion family)"
        or record.get("upstream_commit") != UPSTREAM_COMMIT
        or record.get("test_access") != "EXTERNAL_GPL_EPHEMERAL_ONLY"
        or record.get("public_release") != "EXCLUDED"
        or record.get("redistribution") != "NOT_CLEARED"
    ):
        raise LawfulCorpusError("external CBH source rights/identity invalid")
    if not checkout.is_dir() or checkout.is_symlink():
        raise LawfulCorpusError("external CBH checkout must be direct")
    dirname = record.get("external_fixture_directory")
    stem = record.get("external_fixture_stem")
    oracle_name = record.get("external_oracle_filename")
    for value in (dirname, stem, oracle_name):
        if type(value) is not str or not SAFE.fullmatch(value) or value in (".", ".."):
            raise LawfulCorpusError("unsafe original CBH source component")
    if "/" in dirname or "/" in stem or "/" in oracle_name:
        raise LawfulCorpusError("original CBH filename must not contain separators")
    expected = record.get("external_companion_git_blobs")
    if type(expected) is not dict or len(expected) != 6:
        raise LawfulCorpusError("incomplete original CBH companion registry")
    if set(expected) != {stem + ext for ext in SUFFIXES}:
        raise LawfulCorpusError("CBH companion manifest does not cover exact family")
    if any(type(v) is not str or not SHA40.fullmatch(v) for v in expected.values()):
        raise LawfulCorpusError("CBH companion file has no pinned Git blob")
    family = checkout / "gtest" / dirname
    if not family.is_dir() or family.is_symlink():
        raise LawfulCorpusError("original CBH family directory absent or indirect")
    available = {
        path.name for path in family.iterdir()
        if path.name.startswith(stem + ".") and path.suffix.lower() in SUFFIXES
    }
    if available != set(expected):
        raise LawfulCorpusError("real CBH companion family incomplete or unexpectedly changed")

    license_data = _regular_source(checkout / "LICENSE", max_bytes=1024 * 1024)
    if (
        _raw_git_blob(license_data) != record.get("external_license_git_blob")
        or not license_data.lstrip().startswith(b"GNU GENERAL PUBLIC LICENSE")
    ):
        raise LawfulCorpusError("upstream GPL license changed or not pinned")
    source_data = []
    total = 0
    for name in sorted(expected):
        raw = _regular_source(family / name)
        if _raw_git_blob(raw) != expected[name]:
            raise LawfulCorpusError("original CBH companion Git blob mismatch")
        total += len(raw)
        if total > MAX_FAMILY:
            raise LawfulCorpusError("original CBH family over resource bound")
        source_data.append({
            "file": name,
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "upstream_git_blob": expected[name],
        })
    oracle_data = _regular_source(family / oracle_name)
    expected_oracle = record.get("external_oracle_git_blob")
    if type(expected_oracle) is not str or not SHA40.fullmatch(expected_oracle):
        raise LawfulCorpusError("independent PGN oracle is not pinned")
    if _raw_git_blob(oracle_data) != expected_oracle:
        raise LawfulCorpusError("independent PGN oracle source changed")
    return {
        "source_id": record["id"],
        "source_page": record["source_page"],
        "upstream_commit": UPSTREAM_COMMIT,
        "original_companion_count": len(source_data),
        "original_companions": source_data,
        "original_total_bytes": total,
        "independent_oracle": {
            "file": oracle_name,
            "bytes": len(oracle_data),
            "sha256": hashlib.sha256(oracle_data).hexdigest(),
            "upstream_git_blob": expected_oracle,
        },
        "original_gpl_license_git_blob": record["external_license_git_blob"],
        "redistribution": "NOT_CLEARED",
        "public_release": "EXCLUDED",
        "semantic_import": "NOT_TESTED_BY_SOURCE_ACQUISITION",
    }


def original_cbh_source_receipts(records: tuple[dict, ...], checkout: Path) -> tuple[dict, ...]:
    selected = [x for x in records if "external_companion_git_blobs" in x]
    if len(selected) != 3 or len({x["id"] for x in selected}) != 3:
        raise LawfulCorpusError("expected exactly three independent original CBH families")
    return tuple(sorted(
        (verify_gpl_cbh_family(entry, checkout) for entry in selected),
        key=lambda x: x["source_id"],
    ))


def _exact_head() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"], cwd=ROOT,
            check=True, capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise LawfulCorpusError("exact product checkout not proven") from exc
    head = result.stdout.strip()
    expected = os.environ.get("ACCESSIBLE_CHESS_EXPECTED_HEAD")
    if not SHA40.fullmatch(head) or expected is None or expected != head:
        raise LawfulCorpusError("candidate Git SHA does not match checked-out tree")
    return head


def main() -> None:
    REPORT.unlink(missing_ok=True)
    staging = REPORT.with_suffix(".tmp")
    staging.unlink(missing_ok=True)
    head = _exact_head()
    source = os.environ.get("ACS_37_LIBCBH_ORIGINAL_SOURCE_ROOT")
    if not source:
        raise LawfulCorpusError("original GPL corpus checkout root missing")
    receipts = original_cbh_source_receipts(load_catalog(), Path(source))
    result = {
        "schema": "accessible-chess-section37-original-cbh-provenance-v1",
        "status": "PASS",
        "source_commit_sha": head,
        "upstream_commit": UPSTREAM_COMMIT,
        "original_verified_family_count": len(receipts),
        "families": receipts,
        "no_external_original_files_packaged": True,
        "section37_terminal_done": False,
    }
    try:
        staging.write_text(
            json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(staging, REPORT)
    finally:
        staging.unlink(missing_ok=True)
    print(json.dumps({
        "original_verified_family_count": len(receipts),
        "original_verified_companions": sum(item["original_companion_count"] for item in receipts),
        "source_commit_sha": head,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
