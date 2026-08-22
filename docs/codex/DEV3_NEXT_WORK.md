# AUTO-CHESS DEV3 next work

1. Re-read live PR #65/head, DEV3 coordination files and current open lane PRs before any Product edit. Preserve concurrent progress; if touching work is IN_PROGRESS, remain in SAFE OVERLAP MODE.
2. Preserve the completed BookReader ambiguous durable-target P1 at executable Product head `86a2e6de3e1d89b939d31b6b5aa6de8100505c23`, exact GREEN run/job `32553387781` / `96983670899`: diff hygiene and compile PASS, focused 69/69, full unittest 603/603, full pytest 681 passed + 581 subtests, all 4 new ambiguous-persistence regressions PASS.
3. Durable BookReader progress must fail before publication when a referenced `block:*` or `source:*` target is ambiguous. Failed return-point save must remain atomic. Preserve schema-v2 `fallback_digests` for `index:*` targets and do not guess migration compatibility.
4. Preserve the completed Training revision-integrity P1 and the existing ACSDB/Library/Search/recovery/query-plan + atomic publication packages; do not reopen them without new executable evidence of a defect.
5. Next high-value work after a fresh ownership check: another unclaimed dependency-correct ACSDB/Library/Search P1 or presentation-neutral Books/Training/progress backend contract. Prefer durable library/content/progress integrity and explicit migration/reporting boundaries that reuse the one canonical chess/application core.
6. Do not duplicate DEV2 canonical GameTree/domain, DEV1 UI/Teacher presentation, DEV4 QA/security, or DEV5 integration/promotion ownership.
7. P2 only when no higher P1 remains: workflow actions still emit the Node20-target deprecation warning while GitHub forces Node24. Keep action-version maintenance separate from Product correctness changes.
8. Keep frozen Stage1 release refs untouched. Never create or claim Windows/NVDA evidence from Linux CI.
9. Every substantial Product change requires exact-head focused tests, full unittest, full pytest, compile/diff hygiene and applicable Actions before readiness is claimed.

Current DEV3 ACSDB/Library/Search/recovery/query-plan package: `READY_FOR_INTEGRATION=YES`.
Training revision-bound snapshot slice: `GREEN / HANDOFF RECORDED`.
Books durable reading-progress integrity slices: `GREEN / HANDOFF RECORDED`.
Overall DEV3 Full Product mission: `PARTIAL / CONTINUE ON NEXT SCHEDULED WORK-RUN`.
`NVDA_VERIFIED=NO`.
