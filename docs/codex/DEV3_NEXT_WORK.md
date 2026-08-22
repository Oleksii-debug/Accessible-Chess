# AUTO-CHESS DEV3 next work

1. Re-read live PR #65/head, DEV3 coordination files and current open lane PRs before any Product edit. Preserve concurrent progress; if touching work is IN_PROGRESS, remain in SAFE OVERLAP MODE.
2. Preserve the completed Books durable reading-progress P1 at executable head `7e0d933b1fa6b48318d09683757bb1a54f44ef75`, exact GREEN run/job `32545080795` / `96962002799`: diff hygiene and compile PASS, focused 56/56, full unittest 590/590, full pytest 668 passed + 567 subtests, all 8 new BookReader progress tests PASS.
3. BookReader progress now persists stable semantic targets through the existing BookIndex identity model and fails closed on deleted/ambiguous identities, schema drift or coercive payloads. Keep index-only targets as explicit snapshot-local fallback for blocks without stable source identity.
4. Preserve the prior strict Training snapshot-contract P1 and ACSDB/Library/Search/recovery/query-plan + atomic publication packages; do not reopen them without new executable evidence of a defect.
5. Next high-value work after a fresh ownership check: another unclaimed dependency-correct ACSDB/Library/Search P1 or presentation-neutral Books/Training/progress backend contract. Prefer durable library/content/progress integrity and explicit migration/reporting boundaries that reuse the one canonical chess/application core.
6. Do not duplicate DEV2 canonical GameTree/domain, DEV1 UI/Teacher presentation, DEV4 QA/security, or DEV5 integration/promotion ownership.
7. P2 only when no higher P1 remains: workflow actions emit the Node20-target deprecation warning while GitHub forces Node24. Keep action-version maintenance separate from Product correctness changes.
8. Keep frozen Stage1 release refs untouched. Never create or claim Windows/NVDA evidence from Linux CI.
9. Every substantial Product change requires exact-head focused tests, full unittest, full pytest, compile/diff hygiene and applicable Actions before readiness is claimed.

Current DEV3 ACSDB/Library/Search/recovery/query-plan package: `READY_FOR_INTEGRATION=YES`.
Training strict snapshot-contract slice: `GREEN / HANDOFF RECORDED`.
Books durable reading-progress slice: `GREEN / HANDOFF RECORDED`.
Overall DEV3 Full Product mission: `PARTIAL / CONTINUE ON NEXT SCHEDULED WORK-RUN`.
`NVDA_VERIFIED=NO`.
