#!/usr/bin/env python3
"""Fail-closed technical validation for a SentencePack candidate bundle.

Development/CI utility only. Technical consistency is deliberately separate from
redistribution approval: a structurally valid corpus is not automatically cleared
for public release. The validator reports the release-evidence state explicitly and
can be switched to a strict approval gate with --require-redistribution-approved.

Uses Python standard library only. It requires the disk-backed SQLite companion so
a candidate cannot silently regress from the measured low-memory runtime path to
eager JSON/GZIP loading.
"""
from __future__ import annotations

import argparse
import gzip
import json
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from typing import Any

REQUIRED_METADATA = {
    "schema_version": "2",
    "pack_id": None,
    "source_language": "en",
    "target_language": "uk",
    "provenance": None,
    "license": None,
}

STABLE_IDENTITY_EVIDENCE_NAME = "context-coverage-evidence.stable-identities.json"


def _read_json_object(path: Path, description: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{description} is not readable canonical JSON: {path}") from exc
    if not isinstance(value, dict) or not value:
        raise RuntimeError(f"{description} must be a non-empty JSON object: {path}")
    return value


def _redistribution_state(release_evidence_path: Path | None) -> tuple[bool, str, str | None]:
    if release_evidence_path is None:
        return False, "NOT_APPROVED", None
    if not release_evidence_path.is_file() or release_evidence_path.stat().st_size <= 0:
        raise RuntimeError(f"SentencePack release evidence is missing or empty: {release_evidence_path}")

    document = _read_json_object(release_evidence_path, "SentencePack stable-identity release evidence")
    payload = document.get("Payload")
    if not isinstance(payload, dict):
        raise RuntimeError("SentencePack stable-identity release evidence is missing Payload.")
    approved = payload.get("RedistributionApproved")
    if type(approved) is not bool:
        raise RuntimeError("SentencePack release evidence RedistributionApproved must be an exact JSON boolean.")

    digest = document.get("EvidenceDigestSha256")
    if not isinstance(digest, str) or len(digest) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in digest):
        raise RuntimeError("SentencePack stable-identity release evidence is missing a canonical SHA-256 evidence digest.")

    return approved, "APPROVED" if approved else "NOT_APPROVED", digest.lower()


def _discover_release_evidence(coverage_path: Path, explicit_path: Path | None) -> Path | None:
    if explicit_path is not None:
        return explicit_path
    candidate = coverage_path.parent / STABLE_IDENTITY_EVIDENCE_NAME
    return candidate if candidate.is_file() else None


def validate(
    sqlite_path: Path,
    gzip_path: Path,
    manifest_path: Path,
    coverage_path: Path,
    release_evidence_path: Path | None = None,
    require_redistribution_approved: bool = False,
) -> dict[str, object]:
    for path in (sqlite_path, gzip_path, manifest_path, coverage_path):
        if not path.is_file() or path.stat().st_size <= 0:
            raise RuntimeError(f"Required SentencePack candidate file is missing or empty: {path}")

    # sqlite3.Connection's context manager commits/rolls back but does not close the
    # connection. Use closing() so Windows does not keep pack.sqlite locked after QA.
    with closing(sqlite3.connect(f"file:{sqlite_path.as_posix()}?mode=ro", uri=True)) as db:
        metadata = dict(db.execute("SELECT key, value FROM metadata"))
        for key, expected in REQUIRED_METADATA.items():
            value = metadata.get(key, "").strip()
            if not value:
                raise RuntimeError(f"SQLite metadata is missing {key}")
            if expected is not None and value != expected:
                raise RuntimeError(f"SQLite metadata {key} expected {expected!r}, got {value!r}")
        sentence_count = int(db.execute("SELECT COUNT(*) FROM sentences").fetchone()[0])
        target_count = int(db.execute("SELECT COUNT(*) FROM target_entries").fetchone()[0])
        if sentence_count <= 0 or target_count <= 0:
            raise RuntimeError("SQLite corpus is structurally empty")

    with gzip.open(gzip_path, "rb") as handle:
        prefix = handle.read(1)
        if prefix not in (b"{", b"["):
            raise RuntimeError("Compressed SentencePack does not begin with JSON after decompression")

    manifest = _read_json_object(manifest_path, "SentencePack provenance manifest")
    coverage = _read_json_object(coverage_path, "SentencePack inventory coverage report")
    if coverage.get("sentences") != sentence_count:
        raise RuntimeError(f"Coverage sentence count {coverage.get('sentences')} differs from SQLite {sentence_count}")
    if coverage.get("unique_indexed_oxford_entry_ids") != target_count:
        raise RuntimeError("Coverage target count differs from SQLite target_entries")

    evidence_path = _discover_release_evidence(coverage_path, release_evidence_path)
    redistribution_approved, distribution_status, evidence_digest = _redistribution_state(evidence_path)
    if require_redistribution_approved and not redistribution_approved:
        if evidence_path is None:
            raise RuntimeError(
                "Public SentencePack release was requested, but no explicit stable-identity redistribution evidence was supplied."
            )
        raise RuntimeError(
            "Public SentencePack release was requested, but RedistributionApproved is false. Technical bundle consistency does not authorize redistribution."
        )

    return {
        "validation_scope": "technical_candidate_consistency",
        "pack_id": metadata["pack_id"],
        "license": metadata["license"],
        "sentences": sentence_count,
        "indexed_targets": target_count,
        "sqlite_bytes": sqlite_path.stat().st_size,
        "gzip_bytes": gzip_path.stat().st_size,
        "release_evidence_present": evidence_path is not None,
        "release_evidence_digest_sha256": evidence_digest,
        "redistribution_approved": redistribution_approved,
        "distribution_status": distribution_status,
        "release_boundary": (
            "Technical consistency is not redistribution approval. Public release requires explicit evidence with RedistributionApproved=true."
        ),
    }


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="worddeck-sentence-candidate-") as root_text:
        root = Path(root_text)
        db_path = root / "pack.sqlite"
        # Explicitly close the writer too. This matters on Windows, where an open
        # SQLite handle prevents the negative-path unlink below and temp cleanup.
        with closing(sqlite3.connect(db_path)) as db:
            db.executescript("""
                CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE sentences(sentence_num INTEGER PRIMARY KEY);
                CREATE TABLE target_entries(target_num INTEGER PRIMARY KEY, entry_id TEXT NOT NULL UNIQUE);
            """)
            db.executemany("INSERT INTO metadata(key,value) VALUES(?,?)", [
                ("schema_version", "2"), ("pack_id", "synthetic"),
                ("source_language", "en"), ("target_language", "uk"),
                ("provenance", "synthetic"), ("license", "TEST-ONLY")])
            db.execute("INSERT INTO sentences(sentence_num) VALUES(1)")
            db.execute("INSERT INTO target_entries(target_num,entry_id) VALUES(1,'ox-test')")
            db.commit()

        gzip_path = root / "pack.json.gz"
        with gzip.open(gzip_path, "wt", encoding="utf-8") as handle:
            json.dump({"PackId": "synthetic"}, handle)
        manifest = root / "manifest.json"
        manifest.write_text('{"source":"synthetic"}', encoding="utf-8")
        coverage = root / "coverage.json"
        coverage.write_text('{"sentences":1,"unique_indexed_oxford_entry_ids":1}', encoding="utf-8")

        result = validate(db_path, gzip_path, manifest, coverage)
        if result["sentences"] != 1 or result["redistribution_approved"] is not False:
            raise RuntimeError("Synthetic technical candidate validation did not preserve the non-approved redistribution boundary.")
        if result["distribution_status"] != "NOT_APPROVED":
            raise RuntimeError("Technical candidate without release evidence must be explicitly NOT_APPROVED.")

        evidence = root / STABLE_IDENTITY_EVIDENCE_NAME
        evidence.write_text(
            json.dumps({
                "Payload": {"RedistributionApproved": False},
                "EvidenceDigestSha256": "a" * 64,
            }),
            encoding="utf-8",
        )
        result_with_evidence = validate(db_path, gzip_path, manifest, coverage)
        if result_with_evidence["release_evidence_present"] is not True or result_with_evidence["redistribution_approved"] is not False:
            raise RuntimeError("Validator did not preserve explicit false redistribution evidence.")

        try:
            validate(db_path, gzip_path, manifest, coverage, require_redistribution_approved=True)
        except RuntimeError as exc:
            if "RedistributionApproved is false" not in str(exc):
                raise
        else:
            raise RuntimeError("Strict public-release validation accepted RedistributionApproved=false.")

        evidence.write_text(
            json.dumps({
                "Payload": {"RedistributionApproved": True},
                "EvidenceDigestSha256": "b" * 64,
            }),
            encoding="utf-8",
        )
        approved = validate(db_path, gzip_path, manifest, coverage, require_redistribution_approved=True)
        if approved["distribution_status"] != "APPROVED":
            raise RuntimeError("Strict synthetic approval fixture did not reach APPROVED state.")

        evidence.write_text(
            json.dumps({
                "Payload": {"RedistributionApproved": "false"},
                "EvidenceDigestSha256": "c" * 64,
            }),
            encoding="utf-8",
        )
        try:
            validate(db_path, gzip_path, manifest, coverage)
        except RuntimeError as exc:
            if "exact JSON boolean" not in str(exc):
                raise
        else:
            raise RuntimeError("Validator accepted a non-boolean redistribution approval value.")

        evidence.unlink()
        db_path.unlink()
        try:
            validate(db_path, gzip_path, manifest, coverage)
        except RuntimeError:
            pass
        else:
            raise RuntimeError("Validator accepted a candidate bundle without SQLite")

    print("SentencePack candidate-bundle validator self-test passed: technical consistency and redistribution approval are fail-closed separate states.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sqlite", type=Path)
    parser.add_argument("--gzip", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--coverage", type=Path)
    parser.add_argument("--release-evidence", type=Path)
    parser.add_argument("--require-redistribution-approved", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not all((args.sqlite, args.gzip, args.manifest, args.coverage)):
        parser.error("--sqlite, --gzip, --manifest and --coverage are required unless --self-test is used")
    print(json.dumps(validate(
        args.sqlite,
        args.gzip,
        args.manifest,
        args.coverage,
        release_evidence_path=args.release_evidence,
        require_redistribution_approved=args.require_redistribution_approved,
    ), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
