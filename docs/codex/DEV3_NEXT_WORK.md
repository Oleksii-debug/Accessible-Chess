# AUTO-CHESS DEV3 next work

1. Re-read live PR #65/head and current lane ownership before any Product edit. Preserve same-lane concurrent progress; if touching DEV3 work is IN_PROGRESS, remain in SAFE OVERLAP MODE.
2. Preserve verified executable package head `3f6fd2ff336eab4d0c8b9863da792f1c3d3e28f3` and exact GREEN run/job `32531622900` / `96924650174` for the completed query-plan / large-dataset evidence slice.
3. Next unclaimed P1: audit higher-level import/export application services for concrete atomicity, provenance and lost-update gaps not already covered by `PgnFileService`, `ImportRegistry`, `ImportHistoryService` and ACSDB backup/recovery. Read existing code/tests first. Do not duplicate DEV2 GameTree/domain work or DEV4 ChessBase decoding/security work.
4. Any discovered defect must be closed at the application/storage boundary without creating another canonical chess or GameTree source of truth. Preserve parameterized queries, bounded results, source provenance and failure atomicity.
5. If import/export is already contract-complete, move immediately to DEV3-owned engine-assisted Books/Training/Teacher/progress analytics boundaries: engine evaluation/progress data and backend coordination only. Do not implement DEV1 presentation surfaces or DEV2 canonical GameTree edits.
6. P2 maintenance only when no higher P1 remains: the DEV3 workflow still emits the GitHub Actions Node20-target deprecation warning for `actions/checkout@v4` / `actions/setup-python@v5`; update/pin only after verifying official Node24-capable action releases and without mixing maintenance into Product correctness changes.
7. Keep frozen Stage1 release refs untouched. DEV5 owns cross-lane integration/promotion. Never create or claim a Windows/NVDA candidate from Linux CI.
8. Every substantial Product change requires exact-head focused tests, full unittest, full pytest, compile/diff hygiene and applicable Actions before readiness is claimed.

Current DEV3 ACSDB/Library/Search/recovery + performance-evidence package: `READY_FOR_INTEGRATION=YES`.
Overall DEV3 Full Product mission: `PARTIAL / CONTINUE ON NEXT SCHEDULED WORK-RUN`.
`NVDA_VERIFIED=NO`.
