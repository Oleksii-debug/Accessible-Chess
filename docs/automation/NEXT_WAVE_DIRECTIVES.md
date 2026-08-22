# Accessible Chess autonomous next-wave directives

DIRECTIVE_VERSION: 0006
ISSUED_BY: DEV5 Coordinator/Integrator
EFFECTIVE_FROM_WAVE: 2026-08-22T05:00:00+03:00
SNAPSHOT_SEMANTICS: Workers already running before the effective wave must ignore this directive until their next invocation. Never abandon recoverable in-flight work because a newer directive appears.

## GLOBAL SNAPSHOT
Accepted Stage1 integration remains manual5/integration-20260821 @ 0fa442330bc2bb03636ff9297512da4c29e38684 with exact observed UI Semantic and Stage1 Saturation runs GREEN. No duplicate Stage1 intake or churn.

Full-product remains isolated and package-by-package. No wholesale PR #52/#65/#67/#68/#69 or completion/full-product aggregate merge is authorized. Preserve one canonical chess/GameTree authority and all Windows/NVDA accessibility invariants.

## DEV1 — DIRECTIVE 0006
DEV1_RUN_STATE 20260822-0041 remained IN_PROGRESS before DEV5 cutoff 03:04:21. On next invocation, first terminalize the existing full5/dev1-accessible-shell-20260822 package at one exact SHA. Provide changed-path inventory, focused keyboard/focus/semantic tests and observable applicable CI; set READY_FOR_INTEGRATION only after completion. Do not duplicate chess rules/GameTree/backend ownership and do not contaminate Stage1 lineage.

## DEV2 — DIRECTIVE 0006
Post-cutoff run 20260822-0338 reached executable head 61205a80f819ef70e87ba80fceea108993b5d9c4 and evidence head 6a669dede11509aaaeed0fbb0a0d6c34513680e5, but correctly remains FULL_PRODUCT_DEV2_READY_FOR_INTEGRATION=NO because exact machine evidence is still unobserved. Next invocation: obtain observable exact executable CI for the current canonical GameTree navigation/editing/legality/result/exchange package; synchronize 11_DEV2_HANDOFF_CURRENT and DEV2_RUN_STATE to the exact verified Product SHA; set READY only if required gates are genuinely GREEN. Do not infer success from PR creation alone.

## DEV3 — DIRECTIVE 0006
Post-cutoff head 4d062a5fb7c86afa6a67145e97d773a68f9d2ac9 has observable exact DEV3 Full Product ACSDB CI run 32539411743 SUCCESS. On next invocation, freeze a terminal snapshot before continuing same-lane work: identify executable Product SHA, documentation-only trailing commits, exact changed Product paths, CI run/job and READY status. Explicitly document PGN publication behavior and reconcile it with DEV2 canonical GameTree/PGN contracts and DEV4 lost-update/security assertions. DEV5 will not intake a moving branch.

## DEV4 — DIRECTIVE 0006
Continue strict external-format/PGN security evidence without weakening tests. Current next-wave blockers: reject symlink/reparse import indirection; bound untrusted PGN reads; remove private local paths from serialized report/provenance DTOs; close expected_sha256 final-publication TOCTOU without introducing conflicting publication semantics. Before any Product READY claim, reconcile equivalent DEV3 publication changes and prove the strict regressions against the exact Product head. No tools/qa or strict Windows workflow takeover.

## DEV5 — DIRECTIVE 0006
Take a fresh cutoff first. If any touching worker is IN_PROGRESS before cutoff, remain SAFE OVERLAP. Intake conditions: (1) exact terminal handoff before cutoff; (2) observable exact machine CI; (3) explicit READY at exact Product SHA; (4) no unresolved DEV2/DEV3/DEV4 PGN semantic conflict. Only after DEV2 + DEV3 are terminal and compatible, create a validation-only assembly proving PGN -> canonical GameTree -> ACSDB -> search/open with malformed-input atomicity, no lost updates, provenance, retry/recovery, bounded-resource behavior and full regressions. Advance/create persistent full5 integration only after exact-SHA GREEN validation and auditable provenance. Integrate DEV1 UI only onto the selected canonical backend plane.

PR #54/frozen refs remain protected. Rejected ZIPs are never reused. Fresh Windows candidate requires the complete machine release chain on the exact final audited Product SHA. NVDA_VERIFIED remains NO until Oleksii personally verifies that exact candidate.
