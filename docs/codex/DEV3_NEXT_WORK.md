# AUTO-CHESS DEV3 next work

1. Re-read live PR #65/head, DEV3 coordination files and current open lane PRs before any Product edit. Preserve same-lane concurrent progress; if touching work is IN_PROGRESS, remain in SAFE OVERLAP MODE.
2. Preserve verified executable package head `24817c894fd84cdf0b8e63391249a95c09718e6a` and exact GREEN run/job `32539307522` / `96945995146` for the completed ACSDB backup/restore no-overwrite final-publication race slice. Evidence: focused ACSDB 36/36, full unittest 575/575, full pytest 653 passed + 545 subtests, compile/diff hygiene PASS, both deterministic publication-race tests PASS.
3. The ACSDB `backup_to()` / `restore_backup()` race is now closed: `overwrite=False` uses same-directory atomic create-if-absent publication and cannot silently clobber a creator that wins the final publication window; `overwrite=True` retains replacement semantics; validated backup/restore and peer-temp cleanup remain intact.
4. Next high-value work after a fresh ownership check: take one unclaimed DEV3 backend P1 in engine-assisted Training/Books/Teacher/progress analytics or another dependency-correct ACSDB/Library/Search boundary. Prefer presentation-neutral progress/evaluation data contracts and reuse the one canonical chess/application core; do not create a second rules/GameTree authority.
5. Do not absorb DEV4 QA PR #67 security ownership. Its symlink/reparse, PGN resource-exhaustion, ChessBase report-path privacy and separate PGN optimistic-concurrency evidence remain separate unless live coordination explicitly transfers them. Do not duplicate DEV2 canonical GameTree/domain work, DEV1 UI/Teacher presentation work, or DEV5 integration/promotion.
6. P2 maintenance only when no higher P1 remains: the DEV3 workflow emits the GitHub Actions Node20-target deprecation warning for `actions/checkout@v4` / `actions/setup-python@v5`; update/pin only after verifying official Node24-capable action releases and keep maintenance separate from Product correctness changes.
7. Keep frozen Stage1 release refs untouched. Never create or claim a Windows/NVDA candidate from Linux CI.
8. Every substantial Product change requires exact-head focused tests, full unittest, full pytest, compile/diff hygiene and applicable Actions before readiness is claimed.

Current DEV3 ACSDB/Library/Search/recovery/query-plan package: `READY_FOR_INTEGRATION=YES`.
Completed PGN no-overwrite lost-update slice: `GREEN / HANDOFF RECORDED`.
Completed ACSDB backup/restore publication race slice: `GREEN / HANDOFF RECORDED`.
Overall DEV3 Full Product mission: `PARTIAL / CONTINUE ON NEXT SCHEDULED WORK-RUN`.
`NVDA_VERIFIED=NO`.
