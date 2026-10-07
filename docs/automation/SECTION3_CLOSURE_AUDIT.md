# Section 3 — ACSDB, Library, Search and large game databases — terminal closure audit

Canonical plan authority: **SECTION 3 — ACSDB, Library, Search і великі бази партій**.
Dependency authority: Sections 0–2 are terminally closed; accepted Section-2 post-merge predecessor is `e7bddf0530c8fc1aa41ece2869b1dbdd0144c87b`.

## 3.1 Versioned ACSDB schema

The retained `acs/acsdb.py` authority publishes a versioned SQLite schema and transactional migrations. Canonical game records retain source provenance, metadata, exact positions and loss-aware serialized PGN/GameTree content, including comments and nested variations. Search projections are derivative and integrity guarded; they do not replace canonical records.

Primary regression authorities include `tests/test_acsdb.py`, `tests/test_d07_acsdb_migration_atomicity.py`, `tests/test_v2_library_integrity_repair.py` and semantic PGN/GameTree tests inherited from Section 2.

## 3.2 Search, filters, duplicates and provenance

Canonical authorities are `acs/search_policy.py`, `acs/search_service.py`, `acs/duplicate_detection.py`, `acs/library_source_service.py` and ACSDB indexes/projections. They cover player, event, source, ECO, opening, date, result and exact-position lookup; bounded pagination/cancellation; source provenance; and non-mutating exact/record/tree duplicate evidence.

## 3.3 Import/export, cancellation, indexing and performance

Canonical authorities are `acs/library_import_service.py`, `acs/library_export_service.py`, `acs/import_history_service.py`, `acs/import_registry.py` and the database/search layer. Existing regressions cover transaction ownership, start locks, exact source order, cancellation, export reachability and recovery boundaries.

This finisher adds no second implementation. Its closure workflow executes the retained current contracts on Ubuntu and Windows and runs the retained 100,000-game indexed-search benchmark.

## 3.4 Safe migrations, backup/restore and no-silent-data-loss

`AcsDatabase` migrations are explicit transactions with rollback. Integrity validation covers SQLite integrity, schema identity, foreign keys and derivative search projection consistency. Backup publication is temporary-peer + validation + atomic replacement; restore validates before replacing live authority. Integrity repair fails closed on dirty/stale projections.

## 3.5 Lawful large corpus stress

The accepted Section-2 product tree already has successful run `37676253073` for `lawful-multisource-corpus`, including two pinned lawful PGN sources and a verified 1000-game CC0 Library import -> restart -> search -> export round-trip.

The Section-3 gate additionally executes the retained real CC0 5,000-game source-catalog journey and the 100,000-game indexed ACSDB benchmark. Corpus payloads remain QA-only and are not committed.

## Closure rule

Section 3 may be recorded `DONE — TERMINAL` only when the Section-3 closure workflow is terminally successful for its repository-controllable jobs, the finisher is integrated, and post-merge readback shows no product drift. Under Simplified Section Closure Protocol v3, unavailable external runner/hardware evidence is recorded rather than converted into false product work. Human/NVDA acceptance remains final-product work and is not an intermediate Section blocker.


## 2026-10-07 predecessor repair and executed-gate failures

The previous Section-3 finisher run `37677111348` executed on Ubuntu and Windows.
Its 100k indexed-search + lawful real 5k Library stress job completed SUCCESS, while
both whole-contract jobs reached the test suite and failed on six deterministic
regression-oracle mismatches after upstream safety contracts changed.

This successor is rebuilt directly on the terminal Section-2 integration
`e7bddf0530c8fc1aa41ece2869b1dbdd0144c87b` and changes no Product/runtime code. It repairs only the three stale
test authorities:
- non-text `result` now expects the canonical strict TypeError shared by direct
  ACSDB and GameSearchService rather than treating an integer as an unsupported
  textual result token;
- mocked D06 writers accept the canonical `pre_publish_check` callback added by
  cooperative-cancellation publication fencing;
- concurrent-destination-write tests intercept the canonical
  `_replace_published_path` helper rather than the superseded raw
  `os.replace` implementation detail.

The closure workflow exact-scopes these three test repairs plus this audit and
the workflow itself. Product paths under `acs/`, `tools/`, and `web/` remain
byte-inherited from the accepted Section-2 predecessor.

`SECTION3_PRODUCT_MUTATION=NONE`
`SECTION3_PRIOR_LARGE_STRESS=SUCCESS`
`SECTION3_DONE=NO_PENDING_EXACT_HEAD_QUALIFICATION_AND_INTEGRATION`
