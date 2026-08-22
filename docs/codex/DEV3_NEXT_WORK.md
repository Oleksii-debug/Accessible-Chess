# AUTO-CHESS DEV3 next work

1. Re-read live PR #65, all DEV3 lane state, active DEV1/DEV2/DEV4/DEV5 work and current integration state before any Product edit.
2. The SQLite INTEGER Library/Search scalar P1 at executable head `3dde3a7444c9cf594e92e32f5e084c8969015ad4` is terminal GREEN: run/job `32563847332` / `97009443566`, merge ref `f1134af309c3fe687b039f2aea5c0068b353408c`, focused 87/87, unittest 616/616, pytest 694 + 585 subtests, diff/compile/diagnostic PASS.
3. Preserve its exact contracts: values above `(2**63)-1` reject before SQLite bind; exact max remains valid; booleans/non-ints remain invalid; `source_id` positive-only; `after_game_id` non-negative.
4. Preserve previously terminal-GREEN literal search semantics, stable ACSDB paging/provenance/schema-v3/WAL/backup-recovery/query-plan, atomic PGN/ACSDB publication, Training revision-bound durable CAS progress and Books durable reading-progress integrity.
5. Claim only another unowned dependency-correct P0/P1 in ACSDB/Library/Search/import-export or presentation-neutral Books/Training/progress backend contracts. Prefer correctness, durability, bounded resource behavior and fail-closed public boundaries over cosmetic expansion.
6. Do not duplicate DEV2 canonical GameTree/domain, DEV1 UI/Teacher presentation, DEV4 QA/security or DEV5 integration/promotion ownership. Enter SAFE OVERLAP on any touching IN_PROGRESS work; use independent tests/evidence/backlog refinement instead of competing Product pushes.
7. Read existing code and tests before changes; do not weaken tests for GREEN. Run focused tests plus broad regressions and applicable CI. Keep executable Product commits separate from evidence-only markers where practical.
8. Frozen Stage1 refs remain untouched. Linux CI never establishes personal Windows/NVDA acceptance. `NVDA_VERIFIED=NO` until the user personally verifies an exact fresh Windows candidate.

Current verified executable checkpoint: `3dde3a7444c9cf594e92e32f5e084c8969015ad4` — COMPLETE / GREEN / READY_FOR_INTEGRATION=YES.
