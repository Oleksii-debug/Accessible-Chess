# AUTO-CHESS DEV3 current state

Lane: Full Product engine/analysis + ACSDB / Library / Search / import-export safety + presentation-neutral Books/Training progress backend contracts.

Active Product branch: `auto/dev3-acsdb-stable-paging-20260821`
Draft Product PR: #65 against `codex/full-product-20260821`
Validation-only PR #84: terminal GREEN evidence, CLOSED UNMERGED / DO NOT MERGE.

Current executable Product head: `3dde3a7444c9cf594e92e32f5e084c8969015ad4`.
Implementation commit: `fada1ed8fd31762cb8054ac67124c3a72bd39a28`.
Regression-test commit: `3dde3a7444c9cf594e92e32f5e084c8969015ad4`.

Current completed P1: fail-closed SQLite INTEGER boundaries for presentation-neutral Library/Search query scalars.
- `source_id` and `after_game_id` reject integers above signed 64-bit SQLite INTEGER range before bind.
- Existing strict type rules remain: booleans/non-ints rejected; `source_id` positive-only; `after_game_id` non-negative.
- Exact SQLite maximum `(2**63)-1` remains valid and yields an ordinary empty page when no matching row exists.
- Deterministic regressions cover both overflow paths and valid exact upper boundary.
- No chess rules, canonical GameTree, board, UI, keybinding, Windows candidate or integration target changed.

Terminal exact-base validation:
- validation branch `auto/dev3-search-scalar-ci-evidence-20260822`;
- PR #84 head marker `2220325a1d69cf46bf4611b36f0337378e8ab527` was documentation-only over executable Product base;
- workflow `DEV3 Full Product ACSDB CI` run `32563847332`, job `97009443566` — SUCCESS;
- exact workflow checkout / merge ref `f1134af309c3fe687b039f2aea5c0068b353408c` = Product base plus evidence-only marker;
- diff hygiene PASS; compile PASS;
- focused DEV3 data/Books/Training/Search suite 87/87 PASS, including overflow and max-boundary regressions;
- full unittest 616/616 PASS;
- full pytest 694 passed + 585 subtests PASS;
- SELFTEST PASS; `ACCESSIBLE CHESS 0.4 WEBVIEW2 COMPLETE USER FLOW DIAGNOSTIC PASS`.

Decision: SQLite search-scalar P1 is COMPLETE / GREEN / READY_FOR_INTEGRATION=YES. Previously delivered literal search semantics, stable ACSDB paging/provenance/schema-v3/WAL/backup-recovery/query-plan, atomic PGN/ACSDB publication, Training revision-bound durable CAS progress and Books durable reading-progress integrity remain intact.

SAFE OVERLAP ownership preserved: DEV2 canonical GameTree/domain; DEV1 presentation/UI/Teacher; DEV4 independent QA/security; DEV5 integration/promotion. Frozen Stage1 refs untouched.

Next action: after a fresh live ownership read, claim only another unowned dependency-correct ACSDB/Library/Search or presentation-neutral Books/Training/progress backend P0/P1; otherwise remain SAFE OVERLAP and perform independent validation/evidence. `NVDA_VERIFIED=NO`; no Windows candidate was created by DEV3.
