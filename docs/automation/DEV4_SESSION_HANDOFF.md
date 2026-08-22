# DEV4 SESSION HANDOFF

SESSION: 20260822-2229 Full Product repair / post-publication recovery
STATUS: COMPLETE_WITH_CI_UNOBSERVED
ROLE: DEV4 Product Developer
DIRECTIVE: AUDIT-20260822-1900-01
NVDA_VERIFIED=NO

## Exact state basis

- Product branch: `full5/dev4-import-security-repair-20260822`.
- Product PR #100 remains OPEN/DRAFT/MERGEABLE.
- Run-start head: `f44113ac3c7783aca761c0a7e9044a6cac334cb3`.
- Strict regression commit: `d876d7661ce0ee0b141e9b9944965909967fea4c`.
- Product repair commit: `724cfd025c12e6800cd986b39237ce849542253a`.
- Repo metadata commits follow the Product repair; final exact branch head must be read live after synchronization.
- Accepted Stage1 integration `0fa442330bc2bb03636ff9297512da4c29e38684` remained live-identical and untouched.
- DEV5 PR #66 `abff45ebcc4b5af2a85ab0c456b025b5098c6e29` remained separate and untouched.
- QA PR #67 remains separate; no strict assertion was weakened.
- Exact Product-head Actions/status contexts are absent at this checkpoint: `INCONCLUSIVE`, not GREEN.
- Local focused execution could not start because the execution sandbox cannot resolve `github.com`: `QA_OR_ENVIRONMENT_ONLY`.
- Windows strict WIP=1 untouched.

## Proven and repaired this run

`PROVEN_PRODUCT_DEFECT` — after the expected-hash path had already atomically published its temp file, a failure during snapshot verification or a failure of conflict rollback could still enter `finally` and unlink the `.cas-*.bak` hard-link snapshot. In the rollback-failure case that snapshot can be the only remaining copy of a concurrent writer's newer bytes, so deleting it creates a deterministic recovery/data-loss defect.

The strict tests now inject both failure modes and require the recovery snapshot to survive with the correct content. The Product fix records a preserve-snapshot state after publication whenever safe verification/rollback cannot finish, raises a domain `PgnFileError`, and avoids destructive snapshot cleanup in that state. Normal pre-publication failures and successful verified publication keep their existing cleanup behavior.

## Classification

- `PROVEN_PRODUCT_DEFECT` -> repaired: post-publication verification/rollback could delete the recovery snapshot.
- `QA_OR_ENVIRONMENT_ONLY`: sandbox DNS prevents clean checkout/focused local execution.
- `INCONCLUSIVE`: exact PR #100 CI until checks appear.
- `INCONCLUSIVE`: generic external atomic inode replacement, Windows reparse/hard-link semantics, and directory crash/power-loss durability without exact evidence.
- `HUMAN_ONLY`: exact fresh Windows/NVDA usability.
- No Ctrl+A/Ctrl+C Product defect claim. `NVDA_VERIFIED=NO`.

## Next action

Read final PR #100 head/CI first. Then inspect post-commit cleanup ambiguity only with deterministic evidence: CAS snapshot unlink after successful verified publication and no-clobber temp unlink after successful link publication. Stay out of DEV5 integration, strict Windows, Stage1 release and DEV2 GameTree ownership.
