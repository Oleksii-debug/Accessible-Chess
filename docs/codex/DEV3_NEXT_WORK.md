# AUTO-CHESS DEV3 next work

1. Re-read live PR #65/head, DEV3 coordination files and current open lane PRs before any Product edit. Preserve concurrent progress; if touching work is IN_PROGRESS, remain in SAFE OVERLAP MODE.
2. Preserve the completed strict Training snapshot-contract P1 at executable head `d49482e90089c640869a697dce9fff9abd9f3519`, exact GREEN run/job `32542435950` / `96954884846`: compile/diff hygiene PASS, focused ACSDB 36/36, full unittest 582/582, full pytest 660 passed + 560 subtests, all 7 new Training snapshot tests PASS.
3. The Training persistence boundary now has explicit schema v1, exact required fields, exact scalar types, future-version fail-closed behavior, explicit migration responsibility and no silent default/coercion semantics. Keep chess legality and GameTree authority outside this module.
4. Next high-value work after a fresh ownership check: take another unclaimed DEV3 backend P1 in presentation-neutral Training/Books/Teacher/progress analytics or another dependency-correct ACSDB/Library/Search boundary. Prefer durable evaluation/progress data contracts that reuse the one canonical chess/application core.
5. Do not duplicate DEV2 canonical GameTree/domain, DEV1 UI/Teacher presentation, DEV4 QA/security PR #67, or DEV5 integration/promotion ownership.
6. P2 only when no higher P1 remains: workflow actions emit the Node20-target deprecation warning while GitHub forces Node24. Keep action-version maintenance separate from Product correctness changes.
7. Keep frozen Stage1 release refs untouched. Never create or claim Windows/NVDA evidence from Linux CI.
8. Every substantial Product change requires exact-head focused tests, full unittest, full pytest, compile/diff hygiene and applicable Actions before readiness is claimed.

Current DEV3 ACSDB/Library/Search/recovery/query-plan package: `READY_FOR_INTEGRATION=YES`.
Training strict snapshot-contract slice: `GREEN / HANDOFF RECORDED`.
Overall DEV3 Full Product mission: `PARTIAL / CONTINUE ON NEXT SCHEDULED WORK-RUN`.
`NVDA_VERIFIED=NO`.
