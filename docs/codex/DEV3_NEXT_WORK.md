# AUTO-CHESS DEV3 next work

1. Re-read live PR #65 and validation-only PR #84 before any Product edit. Current executable Product checkpoint is `3dde3a7444c9cf594e92e32f5e084c8969015ad4`; coordination-only commits may make branch HEAD newer without changing executable Product code.
2. First priority is evidence, not new scope: obtain terminal exact-base `DEV3 Full Product ACSDB CI` for PR #84. Do not claim GREEN or readiness from an absent/pending run.
3. If CI is RED, inspect exact failing job/log and repair Product code/tests without weakening expectations. Preserve strict SQLite scalar failure semantics: values above `(2**63)-1` must be rejected before bind, exact max remains valid, booleans remain invalid integers, `source_id` stays positive-only, `after_game_id` stays non-negative.
4. If CI is GREEN, close #84 unmerged; its evidence marker must never enter Product history. Synchronize PR #65 plus DEV3 RUN_STATE/CURRENT_STATE/NEXT_WORK/SESSION_HANDOFF with exact executable head, run/job/merge-ref and test counts.
5. Preserve previously terminal-GREEN literal search semantics, stable ACSDB paging/provenance/schema-v3/WAL/backup-recovery/query-plan, atomic PGN/ACSDB publication, Training revision-bound durable CAS progress and Books durable reading-progress integrity.
6. Do not duplicate DEV2 canonical GameTree/domain, DEV1 UI/Teacher presentation, DEV4 QA/security or DEV5 integration/promotion ownership. Enter SAFE OVERLAP on any touching IN_PROGRESS work.
7. Only after this P1 is terminally verified, claim another unowned dependency-correct ACSDB/Library/Search or presentation-neutral Books/Training/progress backend P1.
8. Frozen Stage1 refs remain untouched. Linux CI never establishes personal Windows/NVDA acceptance. `NVDA_VERIFIED=NO` until the user personally verifies an exact fresh Windows candidate.

Last terminally verified executable checkpoint: `85b88d2efd8fb92f0be5500e5a8da2b86228e46a`, run/job `32561369567` / `97003308118`, focused 85/85, unittest 614/614, pytest 692 + 585 subtests, compile/diff/diagnostic PASS.
Current new P1: `IMPLEMENTED / CI_PENDING / READY_FOR_INTEGRATION=NO`.
