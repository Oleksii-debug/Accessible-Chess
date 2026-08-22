# Accessible Chess autonomous next-wave directives

DIRECTIVE_VERSION: 0015
ISSUED_BY: DEV5 Coordinator/Integrator
EFFECTIVE_FROM_WAVE: 2026-08-22T14:00:00+03:00
SNAPSHOT_SEMANTICS: Workers already running before the effective wave must ignore this directive until their next invocation. Never abandon recoverable in-flight work because a newer directive appears.

## GLOBAL SNAPSHOT
Accepted Stage1 integration remains manual5/integration-20260821 @ 0fa442330bc2bb03636ff9297512da4c29e38684 with previously observed UI Semantic and Stage1 Saturation gates GREEN. No duplicate Stage1 intake or churn.

Full-product remains isolated and package-by-package. DEV1 is still canonically IN_PROGRESS, so SAFE OVERLAP remains mandatory for DEV5 until a later fresh cutoff proves touching lanes terminal. No wholesale evidence-PR merges. Preserve one canonical chess/GameTree authority and all Windows/NVDA accessibility invariants.

## DEV1 — DIRECTIVE 0015
DEV1_RUN_STATE 20260822-0041 remains IN_PROGRESS on full5/dev1-accessible-shell-20260822; PR #68 remains validation-only at c1425c898b3b6d1a4caea6a57a71544ee8582909. On next invocation, terminalize the branch at one exact Product SHA, update canonical RUN_STATE + 10_DEV1_HANDOFF_CURRENT, enumerate exact Product paths, and publish focused keyboard/focus/semantic evidence plus applicable observable CI. Do not duplicate GameTree/chess rules/backend ownership.

## DEV2 — DIRECTIVE 0015
RUN_STATE 20260822-1238 is COMPLETE. Canonical Product head is now 4dd706838881c0e328c7578eada17227de43cf60 with strict v1 GameTree snapshot record and deterministic JSON exchange. Validation PR #83 head 7822926f82354d86f03592c40fcafb2faf9342df has exact DEV2 Full Product Core CI run 32565884179 / job 97014330560 SUCCESS. Snapshot exchange 21/21, navigation 8/8, editing 8/8, insertion 6/6, annotations 8/8, legality 6/6, result/exchange 8/8, GameTree 14/14 and export 7/7 PASS; full unittest 742 OK + 1 SKIP; full pytest 822 PASS + 1 SKIP + 1330 subtests PASS. FULL_PRODUCT_DEV2_READY_FOR_INTEGRATION=YES. PR #83 is evidence-only; DEV5 must consume canonical DEV2 4dd706838... with accepted DEV1 rank/file/keybinding semantics, not merge PR #83 wholesale.

## DEV3 — DIRECTIVE 0015
Live GitHub technical truth reports executable Product base 3dde3a7444c9cf594e92e32f5e084c8969015ad4 with fail-closed signed-64-bit SQLite search-scalar boundaries. Validation PR #84 head 2220325a1d69cf46bf4611b36f0337378e8ab527 has exact DEV3 Full Product ACSDB CI run 32563847332 / job 97009443566 SUCCESS on synthetic merge ref f1134af309c3fe687b039f2aea5c0068b353408c. Focused suite 87/87 PASS; full unittest 616/616 PASS; full pytest 694 PASS + 585 subtests; SELFTEST and complete WebView2 diagnostic PASS. Preserve the isolated ACSDB/Library/Search/recovery/query-plan + deterministic literal search + Training/Books persistence package and keep it separable from DEV2 canonical GameTree and DEV1 presentation ownership. Synchronize canonical 12_DEV3_HANDOFF_CURRENT before another moving-head continuation. PR #84 is evidence-only / DO NOT MERGE.

## DEV4 — DIRECTIVE 0015
Terminal QA handoff 20260822-1200-full-product-qa is COMPLETE at QA head b0967db05bddb438a738a34d278628e069c9cc4b; exact QA-head workflow lookup remains unobserved, so QA stays INCONCLUSIVE. Nine locked blockers govern PGN/ChessBase readiness: (1) symlink/reparse import indirection; (2) bounded untrusted PGN reads and finite source-size boundary; (3) serialized local-path privacy; (4) expected_sha256 commit-boundary TOCTOU; (5) overwrite=False competing-creator lost update; (6) PGN export filesystem-indirection/symlink escape; (7) ChessBase companion-directory I/O failure must not collapse into ordinary no-companion evidence; (8) generic import batch must record importer RuntimeError and continue later sources instead of aborting the batch; (9) ChessBase verify_manifest_unchanged must convert hash/open OSError/PermissionError into explicit failed-verification evidence rather than propagating incidental I/O exceptions. Continue strict deterministic regressions without weakening tests. Product fixes/equivalent reconciliations must preserve canonical DEV2/DEV3 publication semantics and avoid DEV5 integration/Windows strict owner lanes.

## DEV5 — DIRECTIVE 0015
Take a fresh cutoff first. If any touching worker is IN_PROGRESS before cutoff, stay SAFE OVERLAP and do no competing Product push. Once DEV1 is terminal, next safe assembly sequence is: canonical DEV2 4dd706838... + accepted DEV1 ActionRegistry/keybinding semantics; exact GREEN DEV3 3dde3a744... after canonical handoff sync; DEV4 nine defect resolutions/equivalent reconciliations. Then create a validation-only PGN -> canonical GameTree -> ACSDB -> search/open composition and test malformed-input atomicity, bounded-resource behavior, no lost updates, batch-continuation semantics, path privacy/provenance, retry/recovery, signed-64-bit SQLite scalar boundaries, keyboard/focus invariants and full repository regressions. Create/advance persistent full5 integration only after exact-SHA GREEN validation and auditable provenance.

PR #54/frozen refs remain protected. Rejected ZIPs are never reused. Fresh Windows candidate requires the complete machine release chain on the exact final audited Product SHA. NVDA_VERIFIED remains NO until the user personally verifies that exact candidate.
