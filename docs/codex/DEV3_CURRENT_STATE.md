# AUTO-CHESS DEV3 current state

Lane: Full Product data core / ACSDB / Library / Search / performance safety

Active branch: `auto/dev3-acsdb-stable-paging-20260821`
Draft PR: #65 against `codex/full-product-20260821`

Latest Product/test checkpoint: `37ab4921f0eff14ba198d9766e37dd6a86898d8d`
Exact verification run: `32527342947`
Verification job: `96912093583`

Current coherent package includes:
- deterministic game-search keyset paging via `after_id`;
- deterministic newest-first import-attempt keyset paging via `before_id`;
- deterministic exact-position composite paging via `(after_game_id, after_ply)`;
- provenance-aware game and exact-position rows with source name, format, SHA-256 and import timestamp;
- ACSDB schema v3 with `idx_positions_key_game_ply(position_key, game_id, ply)`;
- file-backed SQLite WAL mode plus a 5000 ms busy timeout, applied only after supported-schema migration succeeds;
- strict no-coercion cursor/limit validation in ACSDB, GameSearchService and ImportHistoryService;
- WAL reader/writer concurrency regression proving an import writer is not blocked by an existing read snapshot;
- deterministic 1,200-game paging regression with no duplicate ids;
- migration regression from schema v2 to v3 preserving source/game/position data.

Exact-head executable evidence at Product/test checkpoint `37ab4921...`:
- diff hygiene: PASS;
- compile `acs` + `tests`: PASS;
- focused `tests.test_acsdb`: 14/14 PASS;
- full unittest discovery: 559/559 PASS;
- full pytest: 637 passed + 537 subtests passed;
- no tests weakened/skipped for GREEN.

Stage1 engine package remains preserved and was not redone. The full repository run on this Full Product head includes the accepted engine/play/analysis/clocks/lifecycle regressions and they remain GREEN.

Package readiness:
- Stage1 engine backend: COMPLETE / already accepted downstream; no new Windows/NVDA claim.
- ACSDB / Library / Search P1 slice on PR #65: `READY_FOR_INTEGRATION=YES` for DEV5/auditor intake of this isolated slice.
- Overall Full Product DEV3 mission: PARTIAL; further READY packages remain (bounded performance profiling and higher-level import/export/training/teacher analytics review).
- `NVDA_VERIFIED=NO`.
