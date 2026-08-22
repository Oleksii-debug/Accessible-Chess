# AUTO-CHESS DEV3 next work

1. Re-read live PR #65/head, DEV3 coordination files and current open lane PRs before any Product edit. Preserve concurrent progress; if touching work is IN_PROGRESS, remain in SAFE OVERLAP MODE.
2. Preserve the completed durable Training progress CAS P1 at executable Product head `1ca5784b3ce00837b40888a26dd1e94d8ce754ed`, exact GREEN run/job `32558628088` / `96996629973`: diff/compile PASS, focused 78/78, full unittest 612/612, full pytest 690 passed + 585 subtests, diagnostic PASS.
3. `ExerciseSession` remains the Training semantic authority. `TrainingProgressStore` is infrastructure-only: create-only first publication, exact SHA-256 expected revision for updates, stale-writer rejection, peer writer lock, fsync + atomic replace, strict envelope validation and recovery that preserves the prior durable file on publication failure.
4. Preserve existing schema-v2 Training definition digests, BookReader schema-v2 semantic/fallback targets, live-document mutation guards, ambiguous-target preflight and ACSDB/Library/Search/recovery/query-plan + atomic publication packages; do not reopen them without new executable evidence of a defect.
5. Next high-value work after a fresh ownership check: another unclaimed dependency-correct ACSDB/Library/Search P1 or presentation-neutral Books/Training/progress backend contract. Prefer durable library/content/progress integrity, explicit migrations/reporting and contracts that reuse the one canonical chess/application core.
6. Do not duplicate DEV2 canonical GameTree/domain, DEV1 UI/Teacher presentation, DEV4 QA/security, or DEV5 integration/promotion ownership.
7. PR #77 is validation evidence only and must never be merged into Product. PR #76 was superseded/closed before usable CI because the previous pull-request base filter did not include the exact DEV3 Product branch.
8. P2 only when no higher P1 remains: workflow actions emit the Node20-target deprecation warning while GitHub forces Node24. Keep action-version maintenance separate from Product correctness changes.
9. Keep frozen Stage1 release refs untouched. Never create or claim Windows/NVDA evidence from Linux CI. `NVDA_VERIFIED=NO` until the user personally verifies an exact fresh Windows candidate.
10. Every substantial Product change requires exact-head focused tests, full unittest, full pytest, compile/diff hygiene, complete diagnostic and applicable Actions before readiness is claimed.

Current DEV3 ACSDB/Library/Search/recovery/query-plan package: `READY_FOR_INTEGRATION=YES`.
Training revision-bound snapshot + durable CAS progress slices: `GREEN / HANDOFF RECORDED`.
Books durable reading-progress integrity slices: `GREEN / HANDOFF RECORDED`.
Overall DEV3 Full Product mission: `PARTIAL / CONTINUE ON NEXT SCHEDULED WORK-RUN`.
`NVDA_VERIFIED=NO`.
