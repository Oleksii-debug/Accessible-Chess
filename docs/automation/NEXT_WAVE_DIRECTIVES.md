# Accessible Chess autonomous next-wave directives

DIRECTIVE_VERSION: 0013
ISSUED_BY: DEV5 Coordinator/Integrator
EFFECTIVE_FROM_WAVE: 2026-08-22T12:00:00+03:00
SNAPSHOT_SEMANTICS: Workers already running before the effective wave must ignore this directive until their next invocation. Never abandon recoverable in-flight work because a newer directive appears.

## GLOBAL SNAPSHOT
Accepted Stage1 integration remains manual5/integration-20260821 @ 0fa442330bc2bb03636ff9297512da4c29e38684 with previously observed UI Semantic and Stage1 Saturation gates GREEN. No duplicate Stage1 intake or churn.

Full-product remains isolated and package-by-package. DEV1 is still canonically IN_PROGRESS, so SAFE OVERLAP remains mandatory for DEV5 until a later fresh cutoff proves touching lanes terminal. No wholesale evidence-PR merges. Preserve one canonical chess/GameTree authority and all Windows/NVDA accessibility invariants.

## DEV1 — DIRECTIVE 0013
DEV1_RUN_STATE 20260822-0041 remains IN_PROGRESS on full5/dev1-accessible-shell-20260822; PR #68 remains validation-only at c1425c898b3b6d1a4caea6a57a71544ee8582909. On next invocation, terminalize the branch at one exact Product SHA, update canonical RUN_STATE + 10_DEV1_HANDOFF_CURRENT, enumerate exact Product paths, and publish focused keyboard/focus/semantic evidence plus applicable observable CI. Do not duplicate GameTree/chess rules/backend ownership.

## DEV2 — DIRECTIVE 0013
RUN_STATE 20260822-1042 is COMPLETE. Canonical Product head is now e705c70300c7307255fe2be3ae92f651f103c221 with atomic copy-on-write GameTree move/line comments and NAG annotation editing. Validation PR #80 head 420ccb9164141ad3b04b392305b7c7e77715668b has exact DEV2 Full Product Core CI run 32560686298 / job 97001662361 SUCCESS. Focused annotations 8/8, navigation 8/8, editing 8/8, insertion 6/6, legality 6/6, result/exchange 8/8, GameTree 14/14 and export 7/7 PASS; full unittest 721 PASS + 1 SKIP; full pytest 801 PASS + 1 SKIP + 1308 subtests PASS. FULL_PRODUCT_DEV2_READY_FOR_INTEGRATION=YES. PR #80 is evidence-only; DEV5 must consume canonical DEV2 e705c703... with accepted DEV1 rank/file/keybinding semantics, not merge PR #80 wholesale.

## DEV3 — DIRECTIVE 0013
Live GitHub technical truth reports latest verified executable Product head 1ca5784b3ce00837b40888a26dd1e94d8ce754ed with exact DEV3 Full Product ACSDB CI run 32558628088 / job 96996629973 SUCCESS. All job steps including focused data/reading-progress regressions, full unittest, full pytest and complete diagnostic completed SUCCESS. Documentation-synchronized branch head is 48bd6d2b80b89dfb0f59e61454d2cf0feb6e7246. Preserve the isolated ACSDB/Library/Search/recovery/query-plan + Training/Books persistence package and keep it separable from DEV2 canonical GameTree and DEV1 presentation ownership. Synchronize canonical 12_DEV3_HANDOFF_CURRENT before another moving-head continuation.

## DEV4 — DIRECTIVE 0013
RUN_STATE 20260822-1000-full-product-qa is COMPLETE at QA head 6481f17e0f1b6e602d02ab263414bf8e95f7c477; exact QA-head Actions remain absent, so QA stays INCONCLUSIVE. Eight locked blockers now govern PGN/ChessBase readiness: (1) symlink/reparse import indirection; (2) bounded untrusted PGN reads; (3) serialized local-path privacy; (4) expected_sha256 commit-boundary TOCTOU; (5) overwrite=False competing-creator lost update; (6) PGN export filesystem-indirection/symlink escape; (7) ChessBase companion-directory I/O failure must not collapse into ordinary no-companion evidence; (8) generic import batch must record importer RuntimeError and continue later sources instead of aborting the batch. Continue strict deterministic regressions without weakening tests. Product fixes/equivalent reconciliations must preserve canonical DEV2/DEV3 publication semantics and avoid DEV5 integration/Windows strict owner lanes.

## DEV5 — DIRECTIVE 0013
Take a fresh cutoff first. If any touching worker is IN_PROGRESS before cutoff, stay SAFE OVERLAP and do no competing Product push. Once DEV1 is terminal, next safe assembly sequence is: canonical DEV2 e705c703... + accepted DEV1 ActionRegistry/keybinding semantics; exact GREEN DEV3 1ca5784b... after canonical handoff sync; DEV4 eight defect resolutions/equivalent reconciliations. Then create a validation-only PGN -> canonical GameTree -> ACSDB -> search/open composition and test malformed-input atomicity, bounded-resource behavior, no lost updates, batch-continuation semantics, path privacy/provenance, retry/recovery, keyboard/focus invariants and full repository regressions. Create/advance persistent full5 integration only after exact-SHA GREEN validation and auditable provenance.

PR #54/frozen refs remain protected. Rejected ZIPs are never reused. Fresh Windows candidate requires the complete machine release chain on the exact final audited Product SHA. NVDA_VERIFIED remains NO until the user personally verifies that exact candidate.
