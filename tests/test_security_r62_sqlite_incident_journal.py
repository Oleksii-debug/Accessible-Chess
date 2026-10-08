"""R62 SQLite incident journal: one R22 effect, durable UNKNOWN and readback."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import sqlite3

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from continuum_runtime.leak_response import LeakResponseService
from continuum_runtime.revocation import RevocationAuthority, RevocationKind
from continuum_runtime.watermark_attribution import issue_attribution, opaque_attribution_tag
from acs.protection_incident_response_boundary import (
    IncidentBoundaryDenied, TrustedIncidentBoundary,
)
from acs.protection_incident_sqlite_journal import SqliteIncidentJournal

CASE = "a" * 32
DIGEST = "b" * 64
NOW = datetime(2026, 10, 8, tzinfo=timezone.utc)


def store(tmp_path, active):
    return SqliteIncidentJournal(
        tmp_path / "incident.sqlite3",
        verify_active_revocation=lambda rev_id: rev_id in active,
    )


def test_r62_unknown_case_durable_across_restart(tmp_path):
    active = set()
    first = store(tmp_path, active)
    assert first.status(case_id=CASE, request_digest=DIGEST) == "UNKNOWN_FAIL_CLOSED"
    assert first.reserve(case_id=CASE, request_digest=DIGEST) == "NEW"
    reopened = store(tmp_path, active)
    assert reopened.reserve(case_id=CASE, request_digest=DIGEST) == "UNKNOWN"
    assert reopened.reserve(case_id=CASE, request_digest="c" * 64) == "UNKNOWN"
    assert reopened.status(case_id=CASE, request_digest=DIGEST) == "UNKNOWN_FAIL_CLOSED"


def test_r62_completed_effect_rechecked_after_restore_or_replacement(tmp_path):
    active = {"valid.revocation"}
    journal = store(tmp_path, active)
    assert journal.reserve(case_id=CASE, request_digest=DIGEST) == "NEW"
    assert journal.complete(
        case_id=CASE, request_digest=DIGEST,
        revocation_id="valid.revocation",
    ) is True
    assert journal.status(case_id=CASE, request_digest=DIGEST) == "COMMITTED"
    restarted = store(tmp_path, active)
    assert restarted.status(case_id=CASE, request_digest=DIGEST) == "COMMITTED"
    assert restarted.complete(
        case_id=CASE, request_digest=DIGEST,
        revocation_id="valid.revocation",
    ) is False
    active.remove("valid.revocation")
    active.add("replacement.revocation")
    assert restarted.status(case_id=CASE, request_digest=DIGEST) == "UNKNOWN_FAIL_CLOSED"
    assert restarted.reserve(case_id=CASE, request_digest=DIGEST) == "UNKNOWN"


def test_r62_no_forged_confirmation_or_digest_substitution(tmp_path):
    journal = store(tmp_path, set())
    assert journal.reserve(case_id=CASE, request_digest=DIGEST) == "NEW"
    assert journal.complete(
        case_id=CASE, request_digest=DIGEST, revocation_id="not.active",
    ) is False
    assert journal.complete(
        case_id=CASE, request_digest="c" * 64, revocation_id="not.active",
    ) is False
    assert journal.status(case_id=CASE, request_digest=DIGEST) == "UNKNOWN_FAIL_CLOSED"


def test_r62_atomic_first_reserver_wins_under_parallel_threads(tmp_path):
    journal = store(tmp_path, set())
    def take(_):
        return journal.reserve(case_id=CASE, request_digest=DIGEST)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(take, range(12)))
    assert results.count("NEW") == 1
    assert results.count("UNKNOWN") == 11


@pytest.mark.parametrize("wrong", ["", "xx", True, None, "0" * 31])
def test_r62_malformed_case_and_opaque_digest_denied(tmp_path, wrong):
    journal = store(tmp_path, set())
    with pytest.raises(IncidentBoundaryDenied, match="R62_JOURNAL_INPUT_INVALID"):
        journal.reserve(case_id=wrong, request_digest=DIGEST)


def test_r62_unknown_or_corrupted_schema_never_reinitializes(tmp_path):
    journal = store(tmp_path, set())
    with sqlite3.connect(journal.path) as db:
        db.execute("UPDATE r62_meta SET schema_version=2 WHERE singleton=1")
    with pytest.raises(IncidentBoundaryDenied, match="R62_JOURNAL_SCHEMA_UNSUPPORTED"):
        store(tmp_path, set())


def test_r62_refuse_symlink_journal_and_untrusted_verifier(tmp_path):
    with pytest.raises(IncidentBoundaryDenied, match="R62_EFFECT_READBACK_NOT_CONFIGURED"):
        SqliteIncidentJournal(
            tmp_path / "incident.sqlite3", verify_active_revocation=None)
    original = store(tmp_path, set())
    alias = tmp_path / "untrusted.sqlite3"
    try:
        alias.symlink_to(original.path)
    except (OSError, NotImplementedError):
        pytest.skip("symlink unsupported")
    with pytest.raises(IncidentBoundaryDenied, match="R62_JOURNAL_PATH_UNSAFE"):
        SqliteIncidentJournal(alias, verify_active_revocation=lambda _: True)


def test_r62_exact_neutral_revocation_effect_with_verified_sqlite_restart(tmp_path):
    signing = Ed25519PrivateKey.generate()
    pub = signing.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    artifact = b"synthetic-first-party-image" * 16
    tag = opaque_attribution_tag(
        issuer_secret=b"z"*32, allocation_id="b"*32, build_id="build.one")
    envelope = issue_attribution(
        build_id="build.one", protected_artifact=artifact,
        attribution_tag=tag, key_id="issuer.test", signer=signing.sign,
    )
    r22 = RevocationAuthority()
    def active(revocation_id):
        return any(item.revocation_id == revocation_id and item.active
                   for item in r22.list_active())
    journal = SqliteIncidentJournal(
        tmp_path / "incident.sqlite3", verify_active_revocation=active)
    lineage = {
        "attribution_tag": tag, "build_id": "build.one",
        "device_id": "device.one", "credential_id": "credential.one",
    }
    service = LeakResponseService(
        revocations=r22, trusted_public_keys={"issuer.test": pub},
        lookup_allocation=lambda _tag: dict(lineage),
        corroborate=lambda *_: True,
        approve=lambda *_: True,
    )
    boundary = TrustedIncidentBoundary(
        service=service, authorize_operator=lambda *_: True,
        durable_journal=journal,
    )
    payload = dict(
        operator_session="operator.session", case_id=CASE,
        evidence_sha256=DIGEST, envelope=envelope,
        protected_artifact=artifact, expected_build_id="build.one",
        kind=RevocationKind.CREDENTIAL, now=NOW,
    )
    first = boundary.apply(**payload)
    assert first["status"] == "R62_TARGET_REVOCATION_RECORDED"
    assert first["release_approved"] is False
    assert r22.is_revoked(
        kind=RevocationKind.CREDENTIAL, subject_id="credential.one")
    with sqlite3.connect(journal.path) as db:
        request_digest, state = db.execute(
            "SELECT request_digest,state FROM r62_incidents"
        ).fetchone()
    assert state == "COMMITTED"
    restarted = SqliteIncidentJournal(
        journal.path, verify_active_revocation=active)
    assert restarted.status(
        case_id=CASE, request_digest=request_digest) == "COMMITTED"
    blocked = TrustedIncidentBoundary(
        service=service, authorize_operator=lambda *_: True,
        durable_journal=restarted,
    )
    with pytest.raises(IncidentBoundaryDenied, match="R62_CASE_NOT_NEW"):
        blocked.apply(**payload)
    assert len(r22.history()) == 1
    r22.restore(
        kind=RevocationKind.CREDENTIAL,
        subject_id="credential.one", reason_code="verified-restore",
        now=NOW + timedelta(minutes=1),
    )
    assert restarted.status(
        case_id=CASE, request_digest=request_digest) == "UNKNOWN_FAIL_CLOSED"
    with pytest.raises(IncidentBoundaryDenied, match="R62_CASE_NOT_NEW"):
        blocked.apply(**payload)
    assert len(r22.history()) == 2
