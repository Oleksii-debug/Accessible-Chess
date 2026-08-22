# Accessible Chess autonomous next-wave directives

DIRECTIVE_VERSION: 0007
ISSUED_BY: DEV5 Coordinator/Integrator
EFFECTIVE_FROM_WAVE: 2026-08-22T06:00:00+03:00
SNAPSHOT_SEMANTICS: Workers already running before the effective wave must ignore this directive until their next invocation. Never abandon recoverable in-flight work because a newer directive appears.

## GLOBAL SNAPSHOT
Accepted Stage1 integration remains manual5/integration-20260821 @ 0fa442330bc2bb03636ff9297512da4c29e38684 with exact observed UI Semantic and Stage1 Saturation runs GREEN. No duplicate Stage1 intake or churn.

Full-product remains isolated and package-by-package. No wholesale PR #52/#65/#67/#68/#69 or completion/full-product aggregate merge is authorized. Preserve one canonical chess/GameTree authority and all Windows/NVDA accessibility invariants.

## DEV1 — DIRECTIVE 0007
DEV1_RUN_STATE 20260822-0041 remained IN_PROGRESS through DEV5 cutoff 04:02:44. On next invocation, first terminalize full5/dev1-accessible-shell-20260822 at one exact SHA. Update the canonical handoff/run state, list exact Product paths, focused keyboard/focus/semantic tests and observable applicable CI. Set FULL_PRODUCT_READY_FOR_INTEGRATION only after terminal completion. Do not duplicate GameTree/chess rules/backend ownership or contaminate Stage1 lineage.

## DEV2 — DIRECTIVE 0007
Current PR #69 advanced after DEV5 cutoff; therefore no current-wave intake was authorized. On next invocation, freeze one terminal executable Product SHA for canonical GameTree navigation/editing/legality/result/exchange/PGN work, obtain observable exact machine CI, synchronize handoff/run state to that exact SHA and set READY only if genuinely GREEN. Explicitly document PGN publication/file-write semantics so they can be reconciled with DEV3 and DEV4 findings.

## DEV3 — DIRECTIVE 0007
The older terminal READY slice 70321daf... / run 32528057942 remains valid historical evidence, but the live PR #65 lane has advanced beyond it. On next invocation, freeze the newest coherent Product package at one exact head, separate executable Product commits from documentation-only trailing commits, publish exact CI run/job and READY status, and explicitly state PGN publication semantics. Do not ask DEV5 to intake a moving branch.

## DEV4 — DIRECTIVE 0007
Five locked blockers now govern PGN/external-format readiness: (1) symlink/reparse import indirection; (2) bounded untrusted PGN reads; (3) serialized local-path privacy; (4) expected_sha256 commit-boundary TOCTOU; (5) overwrite=False competing-creator lost-update. Continue deterministic strict regressions without weakening tests. Product fixes must preserve canonical DEV2/DEV3 publication semantics and avoid tools/qa/strict Windows workflow takeover. Exact QA evidence must be observed before calling QA GREEN.

## DEV5 — DIRECTIVE 0007
Take a fresh cutoff first. If any touching worker is IN_PROGRESS before cutoff, stay SAFE OVERLAP. Intake requires terminal pre-cutoff handoff, exact Product SHA, observable exact machine CI, explicit READY and no unresolved DEV2/DEV3/DEV4 PGN semantic conflict. Once backend/security lanes are terminal and compatible, create only a validation-first assembly proving PGN -> canonical GameTree -> ACSDB -> search/open with malformed-input atomicity, bounded-resource behavior, no lost updates, provenance, retry/recovery and full regressions. Advance/create persistent full5 integration only after exact-SHA GREEN validation. Layer DEV1 UI only on the selected canonical backend plane.

PR #54/frozen refs remain protected. Rejected ZIPs are never reused. Fresh Windows candidate requires the complete machine release chain on the exact final audited Product SHA. NVDA_VERIFIED remains NO until Oleksii personally verifies that exact candidate.
