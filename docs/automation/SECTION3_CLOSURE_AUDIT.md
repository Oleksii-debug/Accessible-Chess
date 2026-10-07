# Section 3 closure audit — ACSDB, Library, Search and large game databases

Status: **CLOSURE CANDIDATE — evidence-only; no Product mutation**

Canonical Section plan:
`ACCESSIBLE CHESS — SECTION PLAN ДО ПОВНІСТЮ ЗАВЕРШЕНОГО ПРОДУКТУ`
(updated 2026-10-07T00:44:06Z).

Accepted dependency:
- Section 2 is `DONE — TERMINAL`;
- accepted integrated predecessor: `706e54da9ef157d84b08ea9e1037e0c7a6751db2`.

This closure does not create a second database/search authority. The current
Product already contains the canonical ACSDB/Library/Search implementation; the
closure delta is only this audit plus the exact qualification workflow.

## 3.1 Versioned ACSDB schema

Canonical authority is `acs/acsdb.py`.

Current regressions prove explicit schema versioning, reopen persistence,
forward migration, future-schema rejection without rewrite, canonical games,
positions, source/import provenance, atomic multi-game import and atomic
position batches.

Closure modules:
- `tests.test_acsdb`
- `tests.test_d07_acsdb_migration_atomicity`
- `tests.test_v2_library_integrity_repair`

## 3.2 Search, metadata, filters, duplicates and provenance

The existing ACSDB/Search stack covers player/event/source/ECO/opening/date/
result/position filters, deterministic paging, player identity, source catalog
and fail-closed projection integrity.

Closure modules include:
- `tests.test_v2_library_acsdb_search_v4`
- `tests.test_v2_library_player_identity_search`
- `tests.test_v2_library_date_filter_v5`
- `tests.test_v2_library_search_service_v4`
- `tests.test_d07_search_semantic_equivalence`
- `tests.test_d07_search_scalar_equivalence`
- `tests.test_v2_library_source_catalog`

## 3.3 Import/export, progress/cancel, indexing and performance

The inherited Library services already implement bounded import/export and
search. The closure gate executes import ownership/start-lock/source-order/
final-cancel regressions, export service/reachability regressions, cancellation,
and two deterministic 100,000-game indexed-search benchmarks.

## 3.4 Migration, recovery and no silent data loss

Migration failure is transactionally rolled back; projection corruption fails
closed and explicit repair is tested; import/storage failures do not publish
partial rows. Reopen and SQLite integrity are exercised again by the lawful
real-corpus job.

No separate backup format is invented: SQLite/ACSDB durability and current
Library recovery contracts remain canonical.

## 3.5 Lawful real database stress

The closure workflow reuses the exact hash-pinned lawful Lichess CC0 corpus
oracle already accepted in the Section-2 lineage, derives a verified 1,000-game
sample, and sends that sample through the current Product path:

PGN -> Library import -> close/reopen -> paged search -> filtered PGN export ->
semantic identity comparison -> SQLite integrity.

The source bytes are rechecked unchanged.

## DONE conditions for this candidate

Section 3 may be recorded `DONE — TERMINAL` when:
1. the Section-3 closure gate is terminal on the exact candidate or any
   nonterminal external runner state is handled strictly under Simplified
   Section Closure Protocol v3;
2. no known Section-3 acceptance test is failing;
3. the candidate is canonically integrated;
4. post-integration readback proves the accepted source/build is preserved;
5. `SEQUENTIAL_CLOSURE_STATE.md` records Section 3 terminally so ordinary
   workers skip it.

`SECTION_3_PRODUCT_MUTATION=NONE`
`SECTION_3_REOPEN_POLICY=ONLY_CONCRETE_REGRESSION_INVALID_CLOSURE_CHANGED_CONTRACT_OR_LATER_BREAKAGE`
