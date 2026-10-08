"""R68 SQLite transactional journal product tests; synthetic only, no live HA."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import sqlite3

import pytest

from continuum_runtime.backend_migration import MigrationError, MigrationProof
from acs.protection_backend_migration_journal import SqliteMigrationJournal


def proof():
    return MigrationProof(
        migration_id="migration.one", source_id="old.one",
        target_id="new.one", scope_id="workspace.one", revision=7,
        snapshot_sha256=hashlib.sha256(b"snapshot").hexdigest(),
        backup_sha256=hashlib.sha256(b"backup").hexdigest(),
    )


def journal(tmp_path):
    return SqliteMigrationJournal(tmp_path / "migration.sqlite3")


def test_r68_unknown_is_durable_before_any_external_effect(tmp_path):
    store = journal(tmp_path)
    record = proof()
    assert store.status(record.migration_id) == "UNKNOWN_FAIL_CLOSED"
    assert store.begin(record) is True
    # Fresh process/restart view cannot forget UNKNOWN or authorize NEW again.
    recovered = journal(tmp_path)
    assert recovered.status(record.migration_id) == "RESERVED_UNKNOWN"
    assert recovered.begin(record) is False
    assert recovered.begin(replace(record, target_id="forged-target")) is False
    assert recovered.status(record.migration_id) == "RESERVED_UNKNOWN"


def test_r68_journal_records_only_exact_order_and_source_digest(tmp_path):
    record = proof()
    store = journal(tmp_path)
    assert store.begin(record) is True
    assert store.record(record.migration_id, "STAGED", record.snapshot_sha256) is False
    assert store.record(record.migration_id, "COMMITTED", record.snapshot_sha256) is False
    assert store.record(record.migration_id, "FENCED", "0" * 64) is False
    assert store.record(record.migration_id, "FENCED", record.snapshot_sha256) is True
    assert store.record(record.migration_id, "FENCED", record.snapshot_sha256) is False
    assert store.record(record.migration_id, "STAGED", record.snapshot_sha256) is True
    assert store.record(record.migration_id, "COMMITTED", record.snapshot_sha256) is True
    recovered = journal(tmp_path)
    assert recovered.status(record.migration_id) == "COMMITTED"
    assert recovered.record(record.migration_id, "COMMITTED", record.snapshot_sha256) is False
    assert recovered.begin(record) is False


def test_r68_parallel_reservations_have_single_winner(tmp_path):
    path = tmp_path / "parallel.sqlite3"
    store = SqliteMigrationJournal(path)
    record = proof()
    def reserve(_):
        # Each call creates an independent SQLite transaction/connection.
        return store.begin(record)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(reserve, range(12)))
    assert sum(result is True for result in results) == 1
    assert SqliteMigrationJournal(path).status(record.migration_id) == "RESERVED_UNKNOWN"


def test_r68_unsupported_schema_never_reinitialized_or_silently_migrated(tmp_path):
    store = journal(tmp_path)
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE r68_journal_meta SET schema_version=99 WHERE singleton=1")
    with pytest.raises(MigrationError, match="MIGRATION_JOURNAL_SCHEMA_UNSUPPORTED"):
        journal(tmp_path)


def test_r68_corrupt_phase_fails_closed(tmp_path):
    store = journal(tmp_path)
    record = proof()
    store.begin(record)
    with sqlite3.connect(store.path) as db:
        db.execute("PRAGMA ignore_check_constraints=ON")
        db.execute(
            "UPDATE r68_migration_journal SET phase='FORGED_COMMITTED'"
            " WHERE migration_id=?", (record.migration_id,),
        )
    with pytest.raises(MigrationError, match="MIGRATION_JOURNAL_CORRUPT"):
        store.status(record.migration_id)
    assert store.record(record.migration_id, "COMMITTED", record.snapshot_sha256) is False


def test_r68_no_in_memory_or_dangling_symlink_journal(tmp_path):
    with pytest.raises(MigrationError):
        SqliteMigrationJournal(":memory:")
    with pytest.raises(MigrationError):
        SqliteMigrationJournal(tmp_path / "not-sqlite.txt")
    destination = tmp_path / "destination.sqlite3"
    SqliteMigrationJournal(destination)
    alias = tmp_path / "link.sqlite3"
    try:
        alias.symlink_to(destination)
    except (OSError, NotImplementedError):
        pytest.skip("filesystem symlinks unsupported")
    with pytest.raises(MigrationError, match="MIGRATION_JOURNAL_PATH_UNSAFE"):
        SqliteMigrationJournal(alias)
    destination.unlink()
    with pytest.raises(MigrationError, match="MIGRATION_JOURNAL_PATH_UNSAFE"):
        SqliteMigrationJournal(alias)


@pytest.mark.parametrize("bad", ["UNVERIFIED", "UNKNOWN", "ACK", "SENT", "", True, None])
def test_r68_untrusted_effect_event_never_commits(bad, tmp_path):
    record = proof()
    store = journal(tmp_path)
    store.begin(record)
    with pytest.raises(MigrationError, match="MIGRATION_JOURNAL_RECORD_INVALID"):
        store.record(record.migration_id, bad, record.snapshot_sha256)
    assert store.status(record.migration_id) == "RESERVED_UNKNOWN"


def test_r68_no_unknown_side_effect_retry_even_after_worker_crash(tmp_path):
    store = journal(tmp_path)
    record = proof()
    store.begin(record)
    assert store.record(record.migration_id, "FENCED", record.snapshot_sha256) is True
    recovered = journal(tmp_path)
    assert recovered.status(record.migration_id) == "FENCED"
    assert recovered.begin(record) is False
    # A guessed success cannot bypass the original canonical readback sequence.
    assert recovered.record(record.migration_id, "COMMITTED", record.snapshot_sha256) is False


def test_r68_full_neutral_cutover_with_real_sqlite_journal_recovers_after_restart(tmp_path):
    # Local transactional fixture exercises original neutral MigrationCutover,
    # not a duplicated product migration authority or a live database cutover.
    from continuum_runtime.backend_migration import MigrationCutover
    from acs.protection_backend_migration_binding import (
        CanonicalMigrationOperatorBoundary, TrustedMigrationJob,
    )
    from acs.server_application_boundary import AuthenticatedPrincipal

    signed = proof()
    original_snapshot = b"snapshot"
    verified_backup = b"backup"

    class Source:
        def snapshot(self):
            return 7, original_snapshot
        def fence(self, revision, digest, migration_id):
            return (revision == 7 and digest == signed.snapshot_sha256
                    and migration_id == signed.migration_id)

    class Target:
        staged = None
        def stage(self, current_proof, payload):
            if current_proof != signed:
                return False
            self.staged = payload
            return True
        def readback(self, scope):
            if scope != signed.scope_id or self.staged is None:
                return -1, b"unknown"
            return 7, self.staged

    class Router:
        route = "old.one"
        def read(self, scope):
            if scope != signed.scope_id:
                raise ValueError("unknown scope")
            return self.route
        def compare_and_swap(self, scope, expected, new, migration_id):
            if (scope != signed.scope_id or self.route != expected
                    or migration_id != signed.migration_id):
                return False
            self.route = new
            return True

    source, target, router = Source(), Target(), Router()
    path = tmp_path / "integration.sqlite3"
    job = TrustedMigrationJob(signed, verified_backup)
    actor = AuthenticatedPrincipal(
        "operator.one", "workspace.one", "session.one",
        frozenset({"migration.operator"}), frozenset({"backend.migrate"}),
    )

    def build_boundary():
        neutral = MigrationCutover(
            source=source, target=target, router=router,
            journal=SqliteMigrationJournal(path),
            verify_proof=lambda p: p == signed,
            verify_backup=lambda p, b: (p == signed and b == verified_backup),
        )
        return CanonicalMigrationOperatorBoundary(
            cutover=neutral,
            authorize_operator=lambda current_actor, current_proof: (
                current_actor == actor and current_proof == signed
            ),
            load_approved_job=lambda: job,
        )

    first = build_boundary()
    assert first.execute(actor) == "COMMITTED"
    assert target.staged == original_snapshot
    # A new process reads durable SQL, not an ephemeral in-memory admission.
    recovered = build_boundary()
    assert recovered.reconcile(actor) == "COMMITTED"
    assert recovered.execute(actor) == "UNKNOWN_FAIL_CLOSED"
    assert SqliteMigrationJournal(path).status(signed.migration_id) == "COMMITTED"
