#!/usr/bin/env python3
"""Fail-closed technical validation for a SentencePack candidate bundle.

Development/CI utility only. Technical consistency is deliberately separate from
redistribution approval: a structurally valid corpus is not automatically cleared
for public release. Internal WordDeck coverage evidence may prove corpus identity and
may explicitly record that redistribution is NOT approved, but it cannot grant that
approval itself. A future public-release gate must consume a separately designed and
independently controlled external approval artifact.

Uses Python standard library only. It requires the disk-backed SQLite companion so
a candidate cannot silently regress from the measured low-memory runtime path to
eager JSON/GZIP loading.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
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


def _read_stable_identity_evidence(path: Path) -> tuple[dict[str, Any], dict[str, Any], str]:
    """Read the exact compact C# evidence document and verify its payload digest.

    ContextStableIdentityCoverageEvidenceBuilder hashes the UTF-8 bytes of the
    compact System.Text.Json serialization of Payload, then serializes a document
    whose first property is Payload and second property is EvidenceDigestSha256.
    Hash the exact raw Payload JSON fragment from that generated document rather
    than re-serializing through Python, which avoids cross-runtime escaping/number
    formatting differences while still detecting any content or digest tampering.
    """
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise RuntimeError(f"SentencePack stable-identity release evidence is not readable canonical JSON: {path}") from exc

    prefix = '{"Payload":'
    digest_marker = ',"EvidenceDigestSha256":'
    if not text.startswith(prefix):
        raise RuntimeError("SentencePack stable-identity release evidence is not in canonical compact document form.")

    decoder = json.JSONDecoder()
    try:
        payload_value, payload_end = decoder.raw_decode(text, len(prefix))
    except json.JSONDecodeError as exc:
        raise RuntimeError("SentencePack stable-identity release evidence Payload is not valid canonical JSON.") from exc
    if not isinstance(payload_value, dict) or not payload_value:
        raise RuntimeError("SentencePack stable-identity release evidence is missing Payload.")
    if not text.startswith(digest_marker, payload_end):
        raise RuntimeError("SentencePack stable-identity release evidence document shape is not canonical.")

    digest_start = payload_end + len(digest_marker)
    try:
        digest_value, document_end = decoder.raw_decode(text, digest_start)
    except json.JSONDecodeError as exc:
        raise RuntimeError("SentencePack stable-identity release evidence digest is not valid JSON.") from exc
    if document_end >= len(text) or text[document_end:] != "}":
        raise RuntimeError("SentencePack stable-identity release evidence has trailing or non-canonical document content.")
    if not isinstance(digest_value, str) or len(digest_value) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in digest_value):
        raise RuntimeError("SentencePack stable-identity release evidence is missing a canonical SHA-256 evidence digest.")

    raw_payload_json = text[len(prefix):payload_end]
    actual_digest = hashlib.sha256(raw_payload_json.encode("utf-8")).hexdigest()
    if actual_digest.lower() != digest_value.lower():
        raise RuntimeError("SentencePack stable-identity release evidence digest does not match its exact canonical Payload content.")

    document = {"Payload": payload_value, "EvidenceDigestSha256": digest_value}
    return document, payload_value, digest_value.lower()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _redistribution_state(
    release_evidence_path: Path | None,
    expected_database_sha256: str,
    expected_pack_id: str,
) -> tuple[bool, str, str | None]:
    if release_evidence_path is None:
        return False, "NOT_APPROVED", None
    if not release_evidence_path.is_file() or release_evidence_path.stat().st_size <= 0:
        raise RuntimeError(f"SentencePack release evidence is missing or empty: {release_evidence_path}")

    _, payload, digest = _read_stable_identity_evidence(release_evidence_path)

    database_sha256 = payload.get("DatabaseSha256")
    if not isinstance(database_sha256, str) or database_sha256.lower() != expected_database_sha256.lower():
        raise RuntimeError("SentencePack stable-identity evidence is not bound to the exact SQLite candidate.")
    source_id = payload.get("SourceId")
    if not isinstance(source_id, str) or source_id != expected_pack_id:
        raise RuntimeError("SentencePack stable-identity evidence PackId does not match the exact SQLite candidate.")
    if payload.get("ExactDatabaseIdentityVerified") is not True:
        raise RuntimeError("SentencePack stable-identity evidence did not verify exact database identity.")
    if payload.get("ExactOxford5446Verified") is not True:
        raise RuntimeError("SentencePack stable-identity evidence is not bound to the exact Oxford 5446 universe.")
    if payload.get("CanSupportConservativeStableIdentityCoverageClaim") is not True:
        raise RuntimeError("SentencePack stable-identity evidence is not eligible for conservative stable-ID coverage claims.")

    approved = payload.get("RedistributionApproved")
    if type(approved) is not bool:
        raise RuntimeError("SentencePack release evidence RedistributionApproved must be an exact JSON boolean.")
    if approved:
        raise RuntimeError(
            "Internal stable-identity coverage evidence attempted to grant redistribution approval. "
            "WordDeck coverage tooling is not an external licensing authority; public redistribution requires a separately controlled approval artifact."
        )

    return False, "NOT_APPROVED", digest


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

    database_sha256 = _sha256_file(sqlite_path)

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
    redistribution_approved, distribution_status, evidence_digest = _redistribution_state(
        evidence_path,
        database_sha256,
        metadata["pack_id"],
    )
    if require_redistribution_approved:
        raise RuntimeError(
            "Public SentencePack redistribution cannot be approved by this technical validator. "
            "A separately controlled external approval artifact and gate are required before public release."
        )

    return {
        "validation_scope": "technical_candidate_consistency",
        "pack_id": metadata["pack_id"],
        "license": metadata["license"],
        "sentences": sentence_count,
        "indexed_targets": target_count,
        "sqlite_sha256": database_sha256,
        "sqlite_bytes": sqlite_path.stat().st_size,
        "gzip_bytes": gzip_path.stat().st_size,
        "release_evidence_present": evidence_path is not None,
        "release_evidence_digest_sha256": evidence_digest,
        "redistribution_approved": redistribution_approved,
        "distribution_status": distribution_status,
        "release_boundary": (
            "Technical consistency and internal corpus evidence are not redistribution approval. "
            "Public release requires a separately controlled external approval artifact."
        ),
    }


def _write_test_evidence(path: Path, payload: dict[str, Any], digest_override: str | None = None) -> str:
    raw_payload = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    digest = digest_override or hashlib.sha256(raw_payload.encode("utf-8")).hexdigest()
    path.write_text(
        '{"Payload":' + raw_payload + ',"EvidenceDigestSha256":' + json.dumps(digest) + '}',
        encoding="utf-8",
    )
    return digest


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
        exact_db_hash = _sha256_file(db_path)
        base_payload = {
            "DatabaseSha256": exact_db_hash,
            "SourceId": "synthetic",
            "ExactDatabaseIdentityVerified": True,
            "ExactOxford5446Verified": True,
            "CanSupportConservativeStableIdentityCoverageClaim": True,
            "RedistributionApproved": False,
        }
        exact_evidence_digest = _write_test_evidence(evidence, base_payload)
        result_with_evidence = validate(db_path, gzip_path, manifest, coverage)
        if result_with_evidence["release_evidence_present"] is not True or result_with_evidence["redistribution_approved"] is not False:
            raise RuntimeError("Validator did not preserve explicit false redistribution evidence.")
        if result_with_evidence["sqlite_sha256"] != exact_db_hash:
            raise RuntimeError("Validator did not report the exact SQLite identity used for evidence binding.")
        if result_with_evidence["release_evidence_digest_sha256"] != exact_evidence_digest:
            raise RuntimeError("Validator did not report the exact verified stable-identity evidence digest.")

        _write_test_evidence(evidence, base_payload, digest_override="a" * 64)
        try:
            validate(db_path, gzip_path, manifest, coverage)
        except RuntimeError as exc:
            if "digest does not match" not in str(exc):
                raise
        else:
            raise RuntimeError("Validator accepted stable-identity evidence whose digest did not match its Payload content.")
        _write_test_evidence(evidence, base_payload)

        try:
            validate(db_path, gzip_path, manifest, coverage, require_redistribution_approved=True)
        except RuntimeError as exc:
            if "separately controlled external approval artifact" not in str(exc):
                raise
        else:
            raise RuntimeError("Technical candidate validator incorrectly self-approved public redistribution.")

        forged_approval = dict(base_payload)
        forged_approval["RedistributionApproved"] = True
        _write_test_evidence(evidence, forged_approval)
        try:
            validate(db_path, gzip_path, manifest, coverage)
        except RuntimeError as exc:
            if "not an external licensing authority" not in str(exc):
                raise
        else:
            raise RuntimeError("Validator accepted self-granted redistribution approval from internal coverage evidence.")

        wrong_database = dict(base_payload)
        wrong_database["DatabaseSha256"] = "0" * 64
        _write_test_evidence(evidence, wrong_database)
        try:
            validate(db_path, gzip_path, manifest, coverage)
        except RuntimeError as exc:
            if "exact SQLite candidate" not in str(exc):
                raise
        else:
            raise RuntimeError("Validator accepted release evidence bound to a different SQLite candidate.")

        malformed_boolean = dict(base_payload)
        malformed_boolean["RedistributionApproved"] = "false"
        _write_test_evidence(evidence, malformed_boolean)
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

    print("SentencePack candidate-bundle validator self-test passed: stable-identity Payload digest, exact-candidate consistency and non-approval boundaries are fail-closed; external approval remains separate.")


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
        manifest_path=args.manifest,
        coverage_path=args.coverage,
        release_evidence_path=args.release_evidence,
        require_redistribution_approved=args.require_redistribution_approved,
    ), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
