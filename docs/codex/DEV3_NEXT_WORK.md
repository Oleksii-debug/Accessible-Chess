# AUTO-CHESS DEV3 next work

1. Re-read live PR #65, validation-only PR #81, the exact DEV3 Product head and all DEV3 coordination files before any Product edit. Preserve concurrent progress; if touching work is IN_PROGRESS, remain in SAFE OVERLAP MODE.
2. Current executable Product checkpoint before handoff-only documentation commits: `753ba0ac27e37a944820b2917f2fd2518be283e5`.
3. New P1 awaiting terminal CI classification: literal ACSDB / Library / Search text semantics. `GameSearchService` now escapes SQLite `LIKE` metacharacters `\\`, `%` and `_` and uses explicit `ESCAPE '\\'` clauses while preserving case-insensitive substring search and ECO prefix search.
4. Deterministic regressions cover literal percent, underscore, backslash, source-name combinations and ECO prefix text. `tests.test_search_service` is now part of the focused Full Product DEV3 CI suite.
5. At this checkpoint the connector had not yet returned the applicable exact-head workflow for the new slice. Do not call it GREEN or READY_FOR_INTEGRATION until GitHub Actions for the final documentation-synchronized composition are inspected. Repository-local clone/test execution was unavailable because the runtime container could not resolve `github.com`; an independent SQLite semantic smoke passed for `%`, `_` and `\\`.
6. Validation PR #81 is evidence only and must never be merged. Once terminal CI is observed, record exact run/job/merge-ref/test counts. If GREEN, close #81 unmerged; if RED, inspect the failing job/log and fix root cause without weakening tests.
7. Preserve previous verified executable Product head `1ca5784b3ce00837b40888a26dd1e94d8ce754ed` and exact GREEN run/job `32558628088` / `96996629973` as the last terminally verified checkpoint until the new slice is classified.
8. Preserve existing ACSDB stable paging/provenance/schema-v3/WAL/strict scalars/backup-recovery/query-plan, atomic PGN/ACSDB publication, Training revision-bound snapshots + durable CAS progress, and Books durable progress integrity; do not reopen without new executable evidence.
9. Do not duplicate DEV2 canonical GameTree/domain, DEV1 UI/Teacher presentation, DEV4 QA/security, or DEV5 integration/promotion ownership.
10. After literal-search CI is GREEN, claim another unclaimed dependency-correct ACSDB/Library/Search or presentation-neutral Books/Training/progress backend P1. Prefer durable library/content/progress integrity, explicit migrations/reporting and contracts that reuse the one canonical chess/application core.
11. Keep frozen Stage1 release refs untouched. Never create or claim Windows/NVDA evidence from Linux CI. `NVDA_VERIFIED=NO` until the user personally verifies an exact fresh Windows candidate.

Previous verified DEV3 package: `READY_FOR_INTEGRATION=YES`.
New literal-search P1: `CI_PENDING / NOT YET READY_FOR_INTEGRATION`.
Overall DEV3 Full Product mission: `PARTIAL / CONTINUE ON NEXT SCHEDULED WORK-RUN`.
