# Accessible Chess autonomous next-wave directives

DIRECTIVE_VERSION: 0010
ISSUED_BY: DEV5 Coordinator/Integrator
EFFECTIVE_FROM_WAVE: 2026-08-22T09:00:00+03:00
SNAPSHOT_SEMANTICS: Workers already running before the effective wave must ignore this directive until their next invocation. Never abandon recoverable in-flight work because a newer directive appears.

## GLOBAL SNAPSHOT
Accepted Stage1 integration remains manual5/integration-20260821 @ 0fa442330bc2bb03636ff9297512da4c29e38684 with previously observed UI Semantic and Stage1 Saturation gates GREEN. No duplicate Stage1 intake or churn.

Full-product remains isolated and package-by-package. DEV1 is still canonically IN_PROGRESS, so SAFE OVERLAP remains mandatory for DEV5 until a later fresh cutoff proves touching lanes terminal. No wholesale PR #52/#65/#67/#68/#69/#72/#74 merge is authorized. Preserve one canonical chess/GameTree authority and all Windows/NVDA accessibility invariants.

## DEV1 — DIRECTIVE 0010
DEV1_RUN_STATE 20260822-0041 remains IN_PROGRESS on full5/dev1-accessible-shell-20260822. On next invocation, terminalize the branch at one exact Product SHA, update canonical RUN_STATE + 10_DEV1_HANDOFF_CURRENT, enumerate exact Product paths, and publish focused keyboard/focus/semantic evidence plus applicable observable CI. Do not duplicate GameTree/chess rules/backend ownership. FULL_PRODUCT_READY_FOR_INTEGRATION may become YES only after terminal completion at the same exact SHA.

## DEV2 — DIRECTIVE 0010
RUN_STATE 20260822-0741 preserves canonical Product head 63bae9c1f17032b2046b4137694dc99d195ed9ec at FULL_PRODUCT_DEV2_READY_FOR_INTEGRATION=NO. Validation-only PR #74 head 98a6841348c38ba6d60d7194d1574d9a258236a6 now has observable machine evidence: DEV2 Full Product Core CI run 32552439717 / job 96981254332 is FAILURE. All focused GameTree gates, compile, diff hygiene and full unittest are GREEN; full pytest is 786 passed / 1 skipped / 1294 subtests / exactly 1 failed. The remaining failure is test_board_rank_file_remapping_ui: accepted Stage1 ActionRegistry semantics board.rank_1..8 and board.file_1..8 are absent from DEV2 canonical acs/keybindings.py. This is a cross-lane composition gap, not permission to weaken the test. On next invocation, reconcile those accepted DEV1 keybinding definitions into the validation composition only, preserving DEV2 canonical GameTree work and avoiding broad file overwrite unless exact diff proves safety. Rerun exact aggregate CI; full pytest must be GREEN before READY can change. Do not merge PR #74 directly.

## DEV3 — DIRECTIVE 0010
Live GitHub technical truth now pins latest verified executable Product head 99b5c61c31585d7b2474a050eeb006bf639943dd with exact DEV3 Full Product ACSDB CI run 32550533728 / job 96976421604 SUCCESS. Documentation-synchronized branch head is 79802d22d8c7ed0c387526cfc76c56447400b22a and PR #65 marks READY_FOR_INTEGRATION=YES for the isolated ACSDB/Library/Search/recovery + Training/Books progress package. On next invocation, synchronize canonical Drive handoff to this exact executable Product head/run before advancing the lane again. Do not ask DEV5 to intake a moving or Drive-stale head.

## DEV4 — DIRECTIVE 0010
RUN_STATE 20260822-0657-full-product-qa remains complete at QA head c7c5c9df37c4044469d1cc874e8989aee9a2a677. Exact QA Actions remain unobserved, therefore QA stays INCONCLUSIVE. Six locked blockers govern PGN/external-format readiness: (1) symlink/reparse import indirection; (2) bounded untrusted PGN reads; (3) serialized local-path privacy; (4) expected_sha256 commit-boundary TOCTOU; (5) overwrite=False competing-creator lost update; (6) PGN export symlink-parent escape. Positive replace/fsync failure-recovery/private-temp tests are non-regression evidence, not a seventh defect. Continue strict deterministic regressions without weakening tests. Product fixes/equivalent reconciliations must preserve canonical DEV2/DEV3 publication semantics and avoid tools/qa/strict Windows workflow takeover.

## DEV5 — DIRECTIVE 0010
Take a fresh cutoff first. If any touching worker is IN_PROGRESS before cutoff, stay SAFE OVERLAP and do no competing Product push. Before persistent full5 integration, require: terminal DEV1 exact head; DEV2 aggregate composition GREEN including accepted board rank/file ActionRegistry semantics; DEV3 exact GREEN executable Product head synchronized to Drive; and resolution/reconciliation of the six DEV4 PGN/import blockers. Then build validation-only PGN -> canonical GameTree -> ACSDB -> search/open with malformed-input atomicity, bounded-resource behavior, no lost updates, path privacy/provenance, retry/recovery and full regressions. Create/advance persistent full5 integration only after exact-SHA GREEN validation and auditable provenance.

PR #54/frozen refs remain protected. Rejected ZIPs are never reused. Fresh Windows candidate requires the complete machine release chain on the exact final audited Product SHA. NVDA_VERIFIED remains NO until the user personally verifies that exact candidate.
