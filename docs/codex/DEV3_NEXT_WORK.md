# AUTO-CHESS DEV3 next work

1. Re-read live PR #65, the exact DEV3 Product head, all DEV3 coordination files and current open lane PRs before any Product edit. Preserve concurrent progress; if touching work is IN_PROGRESS, remain in SAFE OVERLAP MODE.
2. Preserve the completed literal ACSDB / Library / Search correctness P1 at verified executable Product head `85b88d2efd8fb92f0be5500e5a8da2b86228e46a`, exact GREEN run/job `32561369567` / `97003308118`, merge ref `d075bc872f40af64a3470fd5d4e869574a8a866a`.
3. Literal search contract: `GameSearchService` escapes SQLite `LIKE` metacharacters `\\`, `%` and `_` and uses explicit `ESCAPE '\\'` clauses while preserving case-insensitive substring search and ECO prefix search. Do not reopen this behavior without new executable evidence of a defect.
4. Exact evidence: diff/compile PASS; focused DEV3 data/Books/Training/Search suite 85/85 PASS; both new literal-search regressions PASS; full unittest 614/614 PASS; full pytest 692 passed + 585 subtests; SELFTEST and complete WebView2 user-flow diagnostic PASS.
5. Preserve existing ACSDB stable paging/provenance/schema-v3/WAL/strict scalars/backup-recovery/query-plan, atomic PGN/ACSDB publication, Training revision-bound snapshots + durable CAS progress, and Books durable progress integrity; do not reopen without new executable evidence.
6. Do not duplicate DEV2 canonical GameTree/domain, DEV1 UI/Teacher presentation, DEV4 QA/security, or DEV5 integration/promotion ownership.
7. Validation PR #82 is terminal evidence only and must remain unmerged. PR #81 was superseded and closed unmerged.
8. Next high-value work after a fresh ownership check: another unclaimed dependency-correct ACSDB/Library/Search P1 or presentation-neutral Books/Training/progress backend contract. Prefer durable library/content/progress integrity, explicit migrations/reporting, bounded deterministic search/index behavior, or failure-atomic import/export contracts that reuse the one canonical chess/application core.
9. P2 only when no higher-value P1 remains: workflow actions emit the Node20-target deprecation warning while GitHub forces Node24. Keep action-version maintenance separate from Product correctness changes.
10. Keep frozen Stage1 release refs untouched. Never create or claim Windows/NVDA evidence from Linux CI. `NVDA_VERIFIED=NO` until the user personally verifies an exact fresh Windows candidate.
11. Every substantial Product change requires exact-head focused tests, full unittest, full pytest, compile/diff hygiene, complete diagnostic and applicable Actions before readiness is claimed.

Current DEV3 ACSDB/Library/Search/recovery/query-plan + literal-search package: `READY_FOR_INTEGRATION=YES`.
Training revision-bound snapshot + durable CAS progress slices: `GREEN / HANDOFF RECORDED`.
Books durable reading-progress integrity slices: `GREEN / HANDOFF RECORDED`.
Overall DEV3 Full Product mission: `PARTIAL / CONTINUE ON NEXT SCHEDULED WORK-RUN`.
`NVDA_VERIFIED=NO`.
