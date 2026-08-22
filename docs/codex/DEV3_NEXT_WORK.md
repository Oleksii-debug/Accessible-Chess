# AUTO-CHESS DEV3 next work

1. Re-read live PR #65/head, DEV3 coordination files and current open lane PRs before any Product edit. Preserve concurrent progress; if touching work is IN_PROGRESS, remain in SAFE OVERLAP MODE.
2. Preserve the completed BookReader index-fallback revision-integrity P1 at executable Product head `99b5c61c31585d7b2474a050eeb006bf639943dd`, exact GREEN run/job `32550533728` / `96976421604`: diff hygiene and compile PASS, focused 65/65, full unittest 599/599, full pytest 677 passed + 581 subtests, all 12 BookReader progress-contract regressions PASS.
3. BookReader snapshots are schema v2. Stable `block:*` and `source:*` semantic targets retain reorder-safe behavior; referenced `index:*` fallbacks carry exact SHA-256 semantic block digests and must fail closed when insertion/edit changes what that numeric fallback means. Schema v1 requires explicit adapter migration and must not be guessed compatible.
4. Preserve the completed Training revision-integrity P1 and the existing ACSDB/Library/Search/recovery/query-plan + atomic publication packages; do not reopen them without new executable evidence of a defect.
5. Next high-value work after a fresh ownership check: another unclaimed dependency-correct ACSDB/Library/Search P1 or presentation-neutral Books/Training/progress backend contract. Prefer durable library/content/progress integrity and explicit migration/reporting boundaries that reuse the one canonical chess/application core.
6. Do not duplicate DEV2 canonical GameTree/domain, DEV1 UI/Teacher presentation, DEV4 QA/security, or DEV5 integration/promotion ownership.
7. P2 only when no higher P1 remains: workflow actions still emit the Node20-target deprecation warning while GitHub forces Node24. Keep action-version maintenance separate from Product correctness changes.
8. Keep frozen Stage1 release refs untouched. Never create or claim Windows/NVDA evidence from Linux CI.
9. Every substantial Product change requires exact-head focused tests, full unittest, full pytest, compile/diff hygiene and applicable Actions before readiness is claimed.

Current DEV3 ACSDB/Library/Search/recovery/query-plan package: `READY_FOR_INTEGRATION=YES`.
Training revision-bound snapshot slice: `GREEN / HANDOFF RECORDED`.
Books durable reading-progress/index-fallback integrity slice: `GREEN / HANDOFF RECORDED`.
Overall DEV3 Full Product mission: `PARTIAL / CONTINUE ON NEXT SCHEDULED WORK-RUN`.
`NVDA_VERIFIED=NO`.
