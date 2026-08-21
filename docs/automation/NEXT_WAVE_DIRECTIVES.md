# Accessible Chess autonomous next-wave directives

DIRECTIVE_VERSION: 0004
ISSUED_BY: DEV5 Coordinator/Integrator
EFFECTIVE_FROM_WAVE: 2026-08-22T03:00:00+03:00
SNAPSHOT_SEMANTICS: Workers already running before the effective wave must ignore this directive until their next invocation. Never abandon in-flight recoverable work merely because a newer directive appears.

## GLOBAL SNAPSHOT
Accepted Stage1 integration remains manual5/integration-20260821 @ 0fa442330bc2bb03636ff9297512da4c29e38684. Do not duplicate work already represented there. No Stage1 Product mutation is requested unless a concrete regression is reproduced or a release-chain step is explicitly authorized.

Full-product integration remains isolated and package-by-package. No wholesale PR #52, completion/full-product-critical-path, PR #65, PR #69 or other aggregate merge is authorized. Canonical core must stay singular; Windows/NVDA invariants remain mandatory.

## DEV1 — DIRECTIVE 0004
Stage1 Release UI/action-routing package is accepted and integrated. On the next invocation that permits a dedicated isolated full-product branch, establish/reuse that branch from the DEV5-selected full-product base only after live coordination. Prioritize reusable accessible application shell and PGN/GameTree Windows UX only when the canonical backend package is terminal. Do not create duplicate board/game state, do not change Stage1 release lineage, and do not claim human accessibility evidence from mocks or semantic tests.

## DEV2 — DIRECTIVE 0004
Live PR #69 is useful but was not eligible for DEV5 intake in wave 0124 because no matching terminal canonical Drive handoff for its full-product head existed at the cutoff. Next invocation: finish the current canonical GameTree/PGN package, then terminalize it with exact SHA, base, changed-path inventory, focused GameTree navigation/edit/legality/PGN round-trip evidence and full unweakened regression CI. Preserve one canonical board/rules/GameTree domain. Do not assume DEV5 consumed any PR #69 work until a later handoff explicitly says so.

## DEV3 — DIRECTIVE 0004
A pre-wave terminal ACSDB/Library/Search/recovery package existed at 70321dafb8fdd1f1aff3197f11d17154ccb942ed with exact DEV3 CI 32528057942 SUCCESS, but live PR #65 advanced beyond that handoff. DEV5 therefore entered SAFE OVERLAP MODE and did not integrate it. Continue current DEV3 work on the same lane; on completion publish one new terminal handoff at the exact final head with focused/full CI and changed-path inventory. Preserve DEV2 ownership of canonical GameTree/domain and DEV4 ownership of external-format security.

## DEV4 — DIRECTIVE 0004
Terminal QA evidence at e65bf755f7dba4090a6396c7086140062f85c5a9 records two strict Product defects in DEV4 ownership: external import symlink/reparse indirection is not fail-closed, and PGN text input has an unbounded full read. Next Product work should fix these contracts without weakening the strict QA tests, while preserving source provenance, atomicity, cancellation/recovery and explicit corruption/unsupported classifications. Keep private-path leakage INCONCLUSIVE until user-visible propagation is proven. Do not take over DEV2 GameTree, DEV3 ACSDB performance, DEV1 UI or Windows strict QA ownership.

## DEV5 — DIRECTIVE 0004
Remain sole cross-lane integrator/coordinator. Next integration attempt must begin with a fresh terminal snapshot. Required dependency order:
1. terminal DEV2 canonical GameTree/PGN package;
2. latest terminal DEV3 ACSDB/Library/Search package;
3. cross-lane validation-only assembly proving PGN -> canonical GameTree -> ACSDB -> search/open, with atomic failure/retry/provenance and full regression evidence;
4. only then create/advance persistent full5 integration if the base and package inventory are independently auditable;
5. external-import/ChessBase integration waits for DEV4 symlink/reparse + bounded-read fixes to terminalize.

PR #52 remains inventory, not a wholesale baseline, until independent evidence accepts a specific exact head. Never merge PR #54 or frozen release refs for convenience. Never reuse a rejected ZIP. A fresh Windows candidate requires the complete machine release chain on the exact final audited Product SHA. NVDA_VERIFIED remains NO until Oleksii personally verifies that exact candidate.
