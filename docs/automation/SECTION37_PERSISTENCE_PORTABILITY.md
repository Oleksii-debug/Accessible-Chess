# Section 37 — Persistence, backup, restore, migrations and user-data portability

Canonical plan: `ACCESSIBLE CHESS — SECTION PLAN ДО ПОВНІСТЮ ЗАВЕРШЕНОГО ПРОДУКТУ`.

Owner directive for this closure run: complete Sections 36 and 37 now. This receipt follows Simplified Section Closure Protocol v3. It does not relabel unfinished predecessor Sections as DONE. Instead, Section 37 is closed against the exact accepted Section-36 integration ancestry and the existing durable-domain authorities listed below. A later integration may reopen Section 37 only if it demonstrably breaks one of these pinned contracts.

## 37.1 Crash-safe state across stateful domains

Section 37 does not create a second domain store.

Existing canonical owners remain authoritative:
- Settings: `acs/settings.py` — versioned schema, bounded parsing, stale-writer fencing, private temp publication, atomic replace and recovery diagnostics.
- Library: `acs/acsdb.py` — SQLite integrity/schema authority, consistent `backup_to` and validated atomic `restore_backup`.
- Books: `acs/book_progress_store.py` — generation/CAS publication, rolling recovery copy, explicit verified backup recovery and durability-unknown handling.
- Training: `acs/training_progress_store.py` — bounded durable progress with crash/recovery contracts.
- Classroom/teaching: `acs/education_workspace_store.py`, `acs/education_records_store.py`, `acs/student_progress_store.py` — versioned CAS/atomic durable state.
- Media: `acs/media_timeline_store.py` — append-only content-bound snapshots and restart recovery.
- Agent jobs/checkpoints: `acs/agent_checkpoint.py` plus Section-21 task/retry/effect contracts — bounded, digest-bound checkpoint state without authority to replay external effects.
- Local account/profile state: `acs/local_profile.py` — versioned atomic profile state with explicit verified recovery. Authentication secrets remain with the canonical credential/account authority and are intentionally never copied into Section-37 portable bundles.

The new `acs/user_data_portability.py` is orchestration only. It is statically gated against SQLite/chess/Classroom/Media owner construction and therefore cannot become a duplicate state authority.

## 37.2 Backup, restore and upgrade preservation

The existing `acs/version2_upgrade.py` / `acs/version2_upgrade_base.py` coordinator remains the canonical whole-user-data upgrade/rollback owner:
- bounded root inventory;
- stable copies and SQLite logical backup;
- checksummed versioned backup manifest;
- tracked-state authentication;
- atomic settings/library publication;
- interrupted-upgrade recovery;
- explicit `rolled_back` phase;
- exact readback validation.

The Section-37 portability coordinator adds a cross-domain typed backup/restore envelope for already-authoritative adapters. Every entry is checksum-bound and size-bounded. Restore preflights every domain before the first mutation, snapshots all rollback points first, verifies post-restore readback, and rolls back already-applied domains in reverse order if a later domain fails.

## 37.3 Accessible export/import of user-owned data

The canonical ActionRegistry now exposes:
- `data.backup`
- `data.restore`
- `data.export`
- `data.import`

`Version2Application` routes these commands through one trusted `bind_user_data_portability` host seam. Modal focus blocks the operation and an unbound host fails closed; no browser/model code receives raw filesystem authority.

Portable bundles include only adapters explicitly marked portable. Any adapter declaring secret material is rejected at registration. Non-portable account/cache/provider state can remain in backup policy without being exported as user-owned portable data.

Existing domain-specific accessible export/import (Settings and Library) remains authoritative and is not duplicated.

## 37.4 Corrupt or partial-state recovery without silent loss

The Section-37 bundle parser fails closed on:
- invalid UTF-8/JSON;
- duplicate JSON keys;
- wrong schema/kind;
- duplicate or unsorted domains;
- invalid sizes;
- malformed Base64;
- checksum mismatch;
- unsupported domains;
- unsupported domain schema after adapter preflight.

No domain is mutated until the whole bundle has passed structural and domain preflight. A mid-restore failure triggers rollback to the exact snapshots captured before mutation. Rollback itself is read back; if rollback cannot re-establish prior state, a distinct hard failure is raised rather than reporting success.

Inherited Settings/Library/Books/Training/Classroom/Media/Profile recovery tests remain in the Section-37 gate.

## 37.5 Cross-version migrations and rollback strategy

Cross-version interpretation belongs to each domain authority. `DomainAdapter.prepare_import` is the only Section-37 migration seam and must return a fully validated current-domain `DomainSnapshot` before any mutation. The whole bundle therefore supports old portable schemas without teaching Section 37 domain semantics.

The existing Version-2 upgrade coordinator retains system-level migration/rollback authority and its journal/backup state machine. Section 37 adds transactional cross-domain import rollback but does not rewrite or bypass the upgrade coordinator.

## Qualification

Dedicated workflow: `.github/workflows/section37-persistence-portability.yml`.

It runs on Ubuntu 22.04 and Windows 2025 and:
1. pins the exact checked-out candidate;
2. performs `git diff --check`;
3. statically proves the new orchestrator does not instantiate duplicate domain authorities;
4. compiles the touched Python boundary;
5. runs the Section-37 bundle/action contract;
6. runs inherited Settings, Book, Training, Classroom, Media, Local Profile and Agent checkpoint persistence regressions;
7. runs ACSDB migration plus Version-2 backup/restore/recovery/stale-writer/migration regressions.

Hosted jobs that remain queued/unstarted are recorded as runner unavailability and are not called GREEN. Any executed RED attributable to this exact Section-37 head must be repaired before terminal closure.

## Closure rule

After exact candidate integration and post-merge zero-delta readback:
- Section 37 = `DONE — TERMINAL`;
- ordinary workers MUST NOT reimplement, polish or repeat-audit this Section;
- reopen only for a concrete demonstrated regression, invalid closure evidence, materially changed acceptance contract, or later integration that demonstrably breaks a pinned Section-37 contract.

Manual NVDA/human acceptance remains whole-product final evidence and does not block this intermediate repository-complete Section under Simplified Section Closure Protocol v3.
