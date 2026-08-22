# AUTO-CHESS DEV3 next work

1. Re-read live PR #65, DEV3 coordination state, active DEV1/DEV2/DEV4/DEV5 work and current integration state before any Product edit.
2. Treat executable head `51d77c4c6f6a70cd47ffb772fff476ce9480d135` as the current verified DEV3 checkpoint: workflow `DEV3 Full Product ACSDB CI` run/job `32568754137` / `97021116904` is SUCCESS; focused 92/92, unittest 622/622, pytest 700 + 599 subtests, diff/compile/diagnostic PASS.
3. Preserve the two latest P1 contracts: ACSDB recovery must reject foreign/forged/structurally invalid SQLite backups while retaining genuine v1/v2 migration support; ImportHistory IDs must stay within positive signed-64-bit SQLite INTEGER bounds before bind, with exact max valid and bool/non-int coercion rejected.
4. Preserve previously terminal-GREEN literal search semantics, stable ACSDB paging/provenance/schema-v3/WAL/query-plan, atomic PGN/ACSDB publication, Training revision-bound durable CAS progress and Books durable reading-progress integrity.
5. Claim only another unowned dependency-correct P0/P1 in ACSDB/Library/Search/import-export or presentation-neutral Books/Training/progress backend contracts. Prefer data-loss prevention, correctness, durability, bounded resource behavior and fail-closed public boundaries over cosmetic expansion.
6. Do not duplicate DEV2 canonical GameTree/domain, DEV1 UI/Teacher presentation, DEV4 QA/security or DEV5 integration/promotion ownership. Enter SAFE OVERLAP on touching IN_PROGRESS work; use independent tests/evidence/backlog refinement instead of competing Product pushes.
7. Read existing code and tests before changes; do not weaken tests for GREEN. Run focused tests plus broad regressions and applicable CI. Keep Product commits recoverable and evidence claims tied to exact SHA/run/job.
8. Frozen Stage1 refs remain untouched. Linux CI never establishes personal Windows/NVDA acceptance. `NVDA_VERIFIED=NO` until the user personally verifies an exact fresh Windows candidate.

Current verified executable checkpoint: `51d77c4c6f6a70cd47ffb772fff476ce9480d135` — COMPLETE / GREEN / READY_FOR_INTEGRATION=YES for delivered DEV3 slices.
