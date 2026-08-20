# ADR-027: ACSDB v3 migration, catalog and recovery invariants

Status: accepted on the completion line.

## Context

The data-forward branch proved a useful ACSDB v3 vertical: normalized players,
events, annotators and openings; semantic GameTree identities; provenance;
duplicate policies; batch import; and recovery copies. Its implementation
predated the completion line's exact-scalar, structural-recovery, legality,
raw-PGN-equivalence, literal-search and transaction hardening. It also assigned
random provenance values and migrated without a mandatory verified backup.

A wholesale merge would therefore regain catalog features by weakening the
current persistence boundary. The v3 contract must instead be rebuilt on top
of the hardened v2 behavior.

## Decision

1. `PRAGMA user_version = 3` owns normalized catalog tables, versioned tree and
   record digests, source provenance, catalog quarantine evidence and schema
   migration evidence. New games and their catalog rows are written in the
   same transaction.
2. Opening a non-empty persistent v1 or v2 database creates and verifies a
   sibling SQLite backup before the first schema statement. Failure to create
   or verify that backup prevents all schema writes.
3. Every required version step and the final migration-evidence row execute in
   one explicit SQLite transaction. An injected failure rolls the whole chain
   back to the exact starting `user_version`; `AcsMigrationError` carries the
   backup location and whether rollback plus integrity verification succeeded.
4. Player, event, annotator and opening catalog identities are deterministic
   versioned SHA-256 values over NFKC-normalized, whitespace-collapsed,
   case-folded semantic text. Game catalog identity uses the existing
   versioned record digest. Automatically assigned source provenance is also
   deterministic; explicit provenance remains authoritative and unique.
5. Migration never deletes or silently repairs an invalid legacy game. A row
   that cannot be parsed, serialized, legally linked and identified remains in
   `games`, is excluded from `game_catalog`, and receives bounded structured
   evidence in `catalog_issues`.
6. New import and direct-storage paths retain all v2 gates: unresolved
   recovery blocks storage, every move must be legally linked, raw PGN must be
   one record-identical game, warning evidence is preserved, and writes are
   atomic.
7. `skip_record` uses the record-digest index only to select candidates. Before
   coalescing it reparses and revalidates the stored PGN. A stale or externally
   altered catalog row can cause a conservative duplicate to be kept, but can
   never cause a false duplicate to be discarded.
8. Text search continues to escape `%`, `_` and `!` as literal characters.
   New annotator catalog search follows the same rule. Public IDs, limits,
   offsets, plies and other scalar boundaries reject Python coercion; FEN keys
   continue to use the canonical structural parser.
9. Atomic batch import validates every game before any product row is written.
   On preparation or storage failure, no source/game/catalog row survives and
   every already-created audit attempt is finalized as failed. Non-atomic mode
   isolates sources and reports each failure explicitly.
10. Manual backup/recovery uses SQLite's online backup API, validates the copy
    before publication, atomically renames it into place and refuses to
    overwrite an existing destination. Read-only database validation does not
    trigger migration.

## Consequences

Valid v1/v2 content migrates without loss and gains deterministic catalog and
identity indexes. Invalid legacy content remains inspectable with explicit
quarantine evidence. Backups consume additional disk space by design and are
not automatically deleted because they are the recovery artifact.

The schema does not claim proprietary ChessBase move decoding, alter GameTree
identity version 1, enable Classroom, touch QA-owned workflows, change the
Stage 1 release lineage or claim human Windows/NVDA verification.
