# AUTO-CHESS DEV3 next work

1. Re-read live PR #65/head, DEV3 coordination files and current open lane PRs before any Product edit. Preserve concurrent progress; if touching work is IN_PROGRESS, remain in SAFE OVERLAP MODE.
2. Preserve the completed BookReader live-document mutation P1 at executable Product head `feaa097bb9c87667132fcede7c0d192503b1d7b9`, exact GREEN run/job `32556145719` / `96990471833`: diff/compile PASS, focused 73/73, full unittest 607/607, full pytest 685 passed + 581 subtests, diagnostic PASS.
3. A BookReader is bound to the exact semantic `BookDocument.blocks` revision used to build its immutable `BookIndex`. Durable save/restore/snapshot must fail closed after in-place source mutation. Persist before edits and restore into a fresh reader; do not silently refresh the index and guess progress identity.
4. Preserve existing schema-v2 `fallback_digests`, ambiguous-target preflight, Training revision-integrity P1 and ACSDB/Library/Search/recovery/query-plan + atomic publication packages; do not reopen them without new executable evidence of a defect.
5. Next high-value work after a fresh ownership check: another unclaimed dependency-correct ACSDB/Library/Search P1 or presentation-neutral Books/Training/progress backend contract. Prefer durable library/content/progress integrity and explicit migration/reporting boundaries that reuse the one canonical chess/application core.
6. Do not duplicate DEV2 canonical GameTree/domain, DEV1 UI/Teacher presentation, DEV4 QA/security, or DEV5 integration/promotion ownership.
7. P2 only when no higher P1 remains: workflow actions still emit the Node20-target deprecation warning while GitHub forces Node24. Keep action-version maintenance separate from Product correctness changes.
8. Keep frozen Stage1 release refs untouched. Never create or claim Windows/NVDA evidence from Linux CI.
9. Every substantial Product change requires exact-head focused tests, full unittest, full pytest, compile/diff hygiene, complete diagnostic and applicable Actions before readiness is claimed.

Current DEV3 ACSDB/Library/Search/recovery/query-plan package: `READY_FOR_INTEGRATION=YES`.
Training revision-bound snapshot slice: `GREEN / HANDOFF RECORDED`.
Books durable reading-progress integrity slices: `GREEN / HANDOFF RECORDED`.
Overall DEV3 Full Product mission: `PARTIAL / CONTINUE ON NEXT SCHEDULED WORK-RUN`.
`NVDA_VERIFIED=NO`.
