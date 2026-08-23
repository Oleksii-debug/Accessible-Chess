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
import hmac
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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_payload_bytes(path: Path) -> bytes:
    """Return the exact canonical Payload JSON bytes used by the C# evidence digest.

    ContextStableIdentityCoverageEvidenceBuilder serializes the document and its
    Payload with the same non-indented System.Text.Json options. Therefore the raw
    nested Payload token in the canonical document is byte-for-byte the material
    hashed by the builder. Requiring that canonical shape lets this validator verify
    the digest without reimplementing System.Text.Json serialization semantics.
    """
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise RuntimeError(f"Stable-identity evidence cannot be read for digest verification: {path}") from exc

    prefix = '{"Payload":'
    if not text.startswith(prefix):
        raise RuntimeError("Stable-identity evidence is not in the canonical compact document shape.")
    start = len(prefix)
    if start >= len(text) or text[start] != "{":
        raise RuntimeError("Stable-identity evidence canonical Payload is not a JSON object.")

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        ch = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                suffix = text[index + 1 :]
                if not suffix.startswith(',"EvidenceDigestSha256":') or not suffix.endswith("}"):
                    raise RuntimeError("Stable-identity evidence is not in the canonical compact document shape.")
                return text[start : index + 1].encode("utf-8")
            if depth < 0:
                break

    raise RuntimeError("Stable-identity evidence canonical Payload object is unterminated.")


def _redistribution_state(
    release_evidence_path: Path | None,
    expected_database_sha256: str,
    expected_pack_id: str,
) -> tuple[bool, str, str | None]:
    if release_evidence_path is None:
        return False, "NOT_APPROVED", None
    if not release_evidence_path.is_file() or release_evidence_path.stat().st_size <= 0:
        raise RuntimeError(f"SentencePack release evidence is missing or empty: {release_evidence_path}")

    document = _read_json_object(release_evidence_path, "SentencePack stable-identity release evidence")
    payload = document.get("Payload")
    if not isinstance(payload, dict):
        raise RuntimeError("SentencePack stable-identity release evidence is missing Payload.")

    digest = document.get("EvidenceDigestSha256")
    if not isinstance(digest, str) or len(digest) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in digest):
        raise RuntimeError("SentencePack stable-identity release evidence is missing a canonical SHA-256 evidence digest.")
    actual_digest = hashlib.sha256(_canonical_payload_bytes(release_evidence_path)).hexdigest()
    if not hmac.compare_digest(actual_digest.lower(), digest.lower()):
        raise RuntimeError("SentencePack stable-identity evidence digest does not match its canonical Payload.")

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

    return False, "NOT_APPROVED", digest.lower()


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

        def write_evidence(payload: dict[str, object], digest_override: str | None = None) -> str:
            payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            canonical_digest = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
            digest_value = digest_override or canonical_digest
            evidence.write_text(
                f'{{"Payload":{payload_json},"EvidenceDigestSha256":"{digest_value}"}}',
                encoding="utf-8",
            )
            return canonical_digest

        base_digest = write_evidence(base_payload)
        result_with_evidence = validate(db_path, gzip_path, manifest, coverage)
        if result_with_evidence["release_evidence_present"] is not True or result_with_evidence["redistribution_approved"] is not False:
            raise RuntimeError("Validator did not preserve explicit false redistribution evidence.")
        if result_with_evidence["sqlite_sha256"] != exact_db_hash:
            raise RuntimeError("Validator did not report the exact SQLite identity used for evidence binding.")

        tampered_payload = dict(base_payload)
        tampered_payload["SourceId"] = "tampered-after-digest"
        write_evidence(tampered_payload, digest_override=base_digest)
        try:
            validate(db_path, gzip_path, manifest, coverage)
        except RuntimeError as exc:
            if "digest does not match its canonical Payload" not in str(exc):
                raise
        else:
            raise RuntimeError("Validator accepted a tampered stable-identity Payload with a stale evidence digest.")

        write_evidence(base_payload)
        try:
            validate(db_path, gzip_path, manifest, coverage, require_redistribution_approved=True)
        except RuntimeError as exc:
            if "separately controlled external approval artifact" not in str(exc):
                raise
        else:
            raise RuntimeError("Technical candidate validator incorrectly self-approved public redistribution.")

        forged_approval = dict(base_payload)
        forged_approval["RedistributionApproved"] = True
        write_evidence(forged_approval)
        try:
            validate(db_path, gzip_path, manifest, coverage)
        except RuntimeError as exc:
            if "not an external licensing authority" not in str(exc):
                raise
        else:
            raise RuntimeError("Validator accepted self-granted redistribution approval from internal coverage evidence.")

        wrong_database = dict(base_payload)
        wrong_database["DatabaseSha256"] = "0" * 64
        write_evidence(wrong_database)
        try:
            validate(db_path, gzip_path, manifest, coverage)
        except RuntimeError as exc:
            if "exact SQLite candidate" not in str(exc):
                raise
        else:
            raise RuntimeError("Validator accepted release evidence bound to a different SQLite candidate.")

        malformed_boolean = dict(base_payload)
        malformed_boolean["RedistributionApproved"] = "false"
        write_evidence(malformed_boolean)
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

    print("SentencePack candidate-bundle validator self-test passed: exact-candidate consistency and canonical evidence digest are bound, internal evidence cannot self-grant redistribution, and external approval remains fail-closed separate.")


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
