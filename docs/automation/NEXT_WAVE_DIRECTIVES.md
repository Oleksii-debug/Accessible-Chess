# Accessible Chess autonomous next-wave directives

DIRECTIVE_VERSION: 0005
ISSUED_BY: DEV5 Coordinator/Integrator
EFFECTIVE_FROM_WAVE: 2026-08-22T04:00:00+03:00
SNAPSHOT_SEMANTICS: Workers already running before the effective wave must ignore this directive until their next invocation. Never abandon in-flight recoverable work merely because a newer directive appears.

## GLOBAL SNAPSHOT
Accepted Stage1 integration remains manual5/integration-20260821 @ 0fa442330bc2bb03636ff9297512da4c29e38684 with exact observed UI Semantic and Stage1 Saturation runs GREEN. No duplicate Stage1 intake or churn is requested.

The full-product plane remains isolated and package-by-package. No wholesale PR #52, PR #65, PR #68, PR #69, PR #67, completion/full-product-critical-path or other aggregate merge is authorized. One canonical core/GameTree must remain authoritative. Windows/NVDA accessibility invariants remain mandatory.

## DEV1 — DIRECTIVE 0005
DEV1_RUN_STATE 20260822-0041 was IN_PROGRESS before DEV5 cutoff 02:06:24, so DEV5 did not race full5/dev1-accessible-shell-20260822. On the next DEV1 invocation, first terminalize the current full-product accessible-shell/Teacher presentation package at one exact SHA with changed-path inventory, focused keyboard/focus/semantic tests and full applicable CI. Explicitly mark READY_FOR_INTEGRATION only after the run is complete. Do not duplicate GameTree/chess rules/backend ownership and do not contaminate Stage1 release lineage.

## DEV2 — DIRECTIVE 0005
Post-cutoff DEV2 run 20260822-0241 completed at a4c9df1d0f21180549cb076ded9de739f91f241c but correctly reports FULL_PRODUCT_DEV2_READY_FOR_INTEGRATION=NO because exact machine evidence was unobserved. Next invocation: obtain exact executable CI for the current GameTree navigation/edit/legality/result/exchange package, keep the package bounded to canonical domain ownership, then synchronize 11_DEV2_HANDOFF_CURRENT + DEV2_RUN_STATE to the exact verified SHA and explicitly set READY_FOR_INTEGRATION only if all required gates are GREEN. Do not assume DEV5 consumed PR #69.

## DEV3 — DIRECTIVE 0005
DEV3 must publish a fresh terminal snapshot before intake. The lane moved beyond terminal 70321d and now touches acs/pgn_service.py as well as ACSDB/query-plan work. Reconcile PGN publication semantics with DEV2 canonical GameTree/PGN contracts and DEV4 security evidence instead of creating a conflicting authority. Terminal handoff must identify the exact executable Product SHA, exact CI run/job, changed Product paths, and whether documentation-only commits followed it. DEV5 will not consume a moving branch.

## DEV4 — DIRECTIVE 0005
Keep strict external-format QA/security ownership. Pre-cutoff blockers remain symlink/reparse fail-closed and bounded PGN input. Post-cutoff evidence additionally flags private-path DTO exposure and PGN publication TOCTOU; retain these as strict tests/evidence and drive Product fixes only in DEV4-owned scope unless another lane has already terminalized an equivalent fix. Before READY_FOR_INTEGRATION, reconcile any PGN publication fix with the latest terminal DEV3 package and avoid duplicate/conflicting os.replace/create-if-absent semantics. No tools/qa or Windows strict workflow takeover.

## DEV5 — DIRECTIVE 0005
Remain sole cross-lane integrator/coordinator. At the next wave, take a fresh cutoff first. Required intake conditions:
1. DEV1/DEV2/DEV3/DEV4 touching package must be terminal before cutoff; any IN_PROGRESS or post-cutoff completion is excluded.
2. DEV2 GameTree/PGN must have exact machine evidence and explicit READY_FOR_INTEGRATION at the exact SHA.
3. DEV3 ACSDB/Library/Search/PGN-publication package must have a fresh terminal handoff and no unresolved semantic conflict with DEV2/DEV4.
4. DEV4 external-import security fixes must be terminal before ChessBase/external-format vertical integration.
5. Only then build a validation-only cross-lane assembly proving PGN -> canonical GameTree -> ACSDB -> search/open with malformed-input atomicity, no lost updates, provenance, retry/recovery and full regression evidence.
6. Create or advance persistent full5 integration only after the validation assembly is exact-SHA GREEN and independently auditable.

PR #52 remains inventory, not a wholesale baseline, until independent evidence accepts a specific exact head. Never merge PR #54 or frozen release refs for convenience. Never reuse a rejected ZIP. A fresh Windows candidate requires the complete machine release chain on the exact final audited Product SHA. NVDA_VERIFIED remains NO until Oleksii personally verifies that exact candidate.
