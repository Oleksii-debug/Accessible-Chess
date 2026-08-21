# AUTO-CHESS DEV3 next work

1. Re-read live PR #65/head, DEV3 coordination files and current open lane PRs before any Product edit. Preserve same-lane concurrent progress; if touching work is IN_PROGRESS, remain in SAFE OVERLAP MODE.
2. Preserve verified executable package head `7c1c0b8092fc487e49d9a654f0f847f6035bedb1` and exact GREEN run/job `32535629207` / `96935870586` for the completed PGN file-publication lost-update slice. Evidence: focused ACSDB 36/36, full unittest 573/573, full pytest 651 passed + 545 subtests, compile/diff hygiene PASS.
3. Next unclaimed P1, if still unowned at the next live check: harden ACSDB `backup_to()` and `restore_backup()` no-overwrite publication. Current code rechecks destination existence and then calls `os.replace()`, leaving a final TOCTOU window where a concurrent creator could be clobbered despite `overwrite=False`. Use an atomic create-if-absent publication boundary or equivalent fail-closed mechanism while preserving same-directory temporary files, SQLite `quick_check`, supported-schema validation, backup consistency and overwrite=True replacement semantics.
4. Add deterministic regression tests that force a competing destination creator into the final publish window for both backup and restore, prove the competing bytes are not replaced, and prove temporary files are cleaned up. Do not weaken existing corrupt/future-schema failure-atomicity tests.
5. Do not absorb DEV4 QA PR #67 security ownership. Its symlink/reparse, PGN resource-exhaustion and ChessBase report-path privacy findings remain separate security work unless live coordination explicitly transfers them. Do not duplicate DEV2 canonical GameTree/domain work or DEV1 UI/Teacher presentation work.
6. If the ACSDB publication race is already claimed or fixed by another worker, move immediately to DEV3-owned engine-assisted Books/Training/Teacher/progress analytics backend boundaries: evaluation/progress data and backend coordination only, using the single canonical chess/application core.
7. P2 maintenance only when no higher P1 remains: the DEV3 workflow still emits the GitHub Actions Node20-target deprecation warning for `actions/checkout@v4` / `actions/setup-python@v5`; update/pin only after verifying official Node24-capable action releases and without mixing maintenance into Product correctness changes.
8. Keep frozen Stage1 release refs untouched. DEV5 owns cross-lane integration/promotion. Never create or claim a Windows/NVDA candidate from Linux CI.
9. Every substantial Product change requires exact-head focused tests, full unittest, full pytest, compile/diff hygiene and applicable Actions before readiness is claimed.

Current DEV3 ACSDB/Library/Search/recovery/query-plan package: `READY_FOR_INTEGRATION=YES`.
Completed PGN no-overwrite lost-update slice: `GREEN / HANDOFF RECORDED`.
Overall DEV3 Full Product mission: `PARTIAL / CONTINUE ON NEXT SCHEDULED WORK-RUN`.
`NVDA_VERIFIED=NO`.
