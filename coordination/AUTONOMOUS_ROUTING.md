# Accessible Chess — Autonomous Routing Control

EPOCH: CHESS-2026-09-08-15
STATE: ACTIVE — FIVE HOURLY WORKERS + WORK COMPLETION OWNER

## Operating invariant
Every worker, Codex Cloud and Work run must reconstruct newest repository/PR/CI/runtime truth before substantive work. Classify inherited targets KEEP, CHANGE, STOP_STALE, COLLISION or PROMOTE. Do not duplicate active ownership.

## Product priority
Converge Version 2 formats/library/books/workflows into one usable Windows/NVDA release candidate without violating Stage 1 release or accessibility boundaries.

Canonical dependency order: GameTree/PGN -> ACSDB/Library -> ChessBase adapters -> Books/Training -> later Teacher/Classroom/Web.

## Live convergence snapshot — 2026-09-08 04:52Z
- #435 remains the single formats umbrella/convergence authority. Do not create a second umbrella.
- #441 remains current V2 runtime/application authority at `3e7dd221e1aafb49f532e547862c2e4357c81162` after #551 and #567 intake.
- #441 Windows Composition, UI Semantic, D01 and data-upgrade workflows are terminal GREEN. The #567 frozen Stage1 checkout fix is therefore effective; Windows checkout byte identity is no longer the blocker.
- #467 remains the canonical broad Formats owner-lock convergence scope. Its prior exact head `7f006c25f1433db5476a123f4d89420449686d1c` terminalized RED on both Ubuntu and Windows at the exact-owner lock before Product tests, while the pinned real ChessBase corpus job passed. Root cause was not a Product regression: W5 had refreshed the expected D07 projection lock to accepted runtime blob `9123b5fb89884ee9a821c89c0898011ae42c1247`, but #467 still physically carried predecessor Product blob `149816ad0ca9a8d240e0b0c7057df15fe6cef0b5`.
- W5 corrected that convergence error without weakening the gate: #467 now physically carries the accepted #441 D07 projection blob `9123b5fb89884ee9a821c89c0898011ae42c1247` and retains the same exact lock. Current exact head is `d135f517d6f1c98da97134222182260d717095d9`; Formats run `34188684000` is in progress and must terminalize before intake.
- #454 is STOP_STALE/evidence-only. Its narrow older table must not be selectively intaken or continued as a competing workflow authority; #467 subsumes that lock-refresh scope.
- Inherited W1 D06 framer/preflight failures on #441/#467 currently stop at their ancestry/scope proof before Product tests. Treat them as stale topology evidence unless a current Product regression is independently demonstrated; do not misclassify them as Product RED.
- #536 remains sole P0 external-review isolation Product owner and is TERMINAL GREEN / PROMOTE-ready. Intake remains gated behind refreshed broad Formats convergence.
- #543 remains terminal-green Book->Board repaint/focus baseline. #560 remains terminal-green Library->PGN visible-route refresh and PROMOTE-ready for bounded intake after broad Formats is restored.
- #551 and #567 are COMPLETED/DO-NOT-REPEAT and already merged into #441.
- #448 remains shipped-V1 executable-local data bridge and must terminalize before fresh runtime-data recomposition.
- #565 remains required-resource package-preflight Product repair; #558 prepares payload and #530 assembles. None alone is release authority.
- #562 owns bounded D06 resume-lock TOCTOU; #555 owns D07 complete filtered-export streaming; D06 remains sole PGN serializer.
- #518 owns Book progress/open transaction atomicity.
- #491 owns persisted language; #532 is downstream native-dialog localization.
- #510/#515 own Markdown/HTML semantic lists; #541 owns bounded EPUB semantic ingress.
- #488 owns ImportRegistry path privacy. #478 owns current-base Library source/provenance convergence.

## Completed / DO NOT REPEAT
- #436 canonical bounded PGN ingress for BookTraining.
- #437 dirty-PGN open/discard guard.
- #438 V2 UI semantic/accessibility CI expansion.
- #439 Windows file-workflow UI-thread fail-closed repair.
- #443 owner-bound dirty-PGN discard confirmation.
- #444/#447 nested-comment PGN convergence work.
- #457 package-preflight Windows superscript-device-alias repair.
- #461 D01 PGN convergence-aware CI topology repair merged into #441.
- #543 Book->Board ordered Stage1 repaint/focus baseline.
- #551 terminal Library-import UI wakeup self-recovery, merged into #441.
- #567 frozen Stage1 Git-blob checkout normalization, merged into #441.

## STOP_STALE / collision decisions
- #434 predecessor umbrella; #435 is successor.
- #440/#442/#445/#446 old W4 snapshots/attempts.
- #450 older V1 executable-data bridge; #448 is current.
- #453 partial duplicate of D07 lock repair.
- #454 is superseded for D07 projection convergence by canonical broad #467; keep only as evidence.
- #465/#477 duplicate D01 topology repairs; #461 is canonical.
- #464/#466/#480 stale runtime/package ancestry. Never package from these.
- #482/#483/#485/#486/#487/#489 stale/duplicate language implementations; #491 is canonical.
- #496/#499 duplicate Book-board implementations.
- #512 duplicate HTML-list implementation; #515 is canonical.
- #535/#542/#554 closed external-review predecessors; #536 is current terminal-green Product owner.
- #546/#566 stale/evidence-only external-review branches.
- #559/#561 review-engine evidence only; neither is Product release authority.
- #552/#557 closed Library->PGN predecessors; #560 is current terminal GREEN.
- #538 is RED-parent/evidence lineage; #565 is current required-resource Product repair.
- #556 duplicate/evidence only; #551 is merged and DO-NOT-REPEAT.
- #563/#564 duplicates of #518.

## Active reservations / collision boundaries
- #441 owns Version2Application, runtime/release bootstrap, Windows composition and shared application boundary.
- #448 owns shipped-V1 executable-local data bridge.
- #467 solely owns broad Formats integrated owner-lock/evidence topology and bounded convergence of the accepted D07 Library projection from #441. Do not weaken locks or revive #454 as a competing authority.
- #536 owns terminal-green P0 external-review Product delta awaiting selective convergence intake.
- #543/#560 own accepted Book->Board baseline and bounded Library->PGN route refresh respectively.
- #491/#532 own persisted language and native-dialog localization in dependency order.
- #498 owns composition-root startup cleanup.
- #510/#515/#541 own Markdown/HTML/EPUB semantic ingestion scopes.
- #518 owns Book progress/open command atomicity.
- #488 owns ImportRegistry path privacy.
- #511/#565/#558/#530 own existing package/preflight layers.
- #562 owns only D06 resume-lock validation/open identity TOCTOU.
- #555 owns only D07 lazy complete filtered export; D06 stays sole PGN writer.
- #478 owns current-base Library source/provenance catalog convergence.

## Current release gates
1. **Broad Formats exact-head gate:** #467@`d135f517...` must terminalize after W5 converged the accepted current D07 projection Product blob and exact owner lock while preserving Book Progress, PGN streaming, full-suite and pinned external evidence topology.
2. **Runtime automation:** #441@`3e7dd221...` Windows Composition, UI Semantic, D01 and data workflows are terminal GREEN. Its earlier broad Formats RED was stale-owner topology, not Product failure.
3. **Windows frozen blob checkout: COMPLETED #567.** Exact-head dual-OS W4 contract GREEN and effective after merge into #441. Do not create another checkout-normalization owner.
4. **P0 external review: PROMOTE #536.** Exact-head dual-OS Windows Composition terminal SUCCESS. Selectively compose only after refreshed broad Formats is GREEN/intaken and ancestry/collision review passes.
5. **Accessibility route refresh: PROMOTE #560** on accepted #543 baseline after the same convergence review.
6. #448 must terminalize before one fresh runtime-data recomposition. Never revive #464/#466.
7. #491 then #532 must terminalize before one persisted/localized Windows language experience is claimed.
8. #498 must close startup cleanup without creating a second runtime owner.
9. #510/#515 and selectively accepted #541 must terminalize before broader Books ingestion claims.
10. #518 must terminalize before Book progress/open transactions are considered durable.
11. #488 plus relevant privacy/security children, including #562 where applicable, must terminalize before release intake.
12. #555 may be intaken only after exact-head dual-OS and collision review and must not change D06 serialization authority.
13. Package path remains #511 -> #565 plus #558 -> #530 with exact packaged-runtime evidence. No rejected ZIP may be reused.
14. Produce exactly one fresh Windows candidate/package from the refreshed non-stale stack.
15. Human NVDA acceptance remains open: `NVDA_VERIFIED=NO` until Oleksii personally tests that exact candidate.
16. ChessBase-family capability truth remains SUPPORTED/PARTIAL/UNSUPPORTED/BLOCKED; unsupported adapters must not block unrelated desktop release work.

## Worker routing
### W1 — Formats / GameTree / interoperability
CHANGE. #444/#447 are complete. Continue disjoint owners such as #547 bounded model materialization and #562 resume-lock TOCTOU only after real exact-head evidence. Do not duplicate #467/D07 owner convergence. D06 framer/preflight ancestry-only failures are not Product authority by themselves.

### W2 — Library / database / books / training content
PROMOTE dependency-safe work only. #448 is the data-release dependency. Continue #518, #510/#515/#541, #555 and #478 in their reserved scopes. Keep #468 blocked until identity/security is resolved.

### W3 — User workflows / desktop composition
PROMOTE. #536 is terminal GREEN and must not be reimplemented. Hold selective intake until #467 broad Formats exact-head terminalizes and is selectively composed into #441; then perform bounded ancestry/collision review and intake without duplicating #491/#532, #518 or W4 #543/#560.

### W4 — Windows / NVDA / accessibility / package QA
PROMOTE. #567 is complete, merged and proven effective on current #441. #543/#560 remain accepted terminal-green accessibility packages. Do not spawn another frozen-blob or Library->PGN owner. After runtime/data/security stack converges, build one fresh candidate and exact-machine QA. Never reuse rejected packages or claim human NVDA verification.

### W5 — Integration / release / coordination
PROMOTE. W5 confirmed prior #467 RED was caused by incomplete convergence: the workflow expected accepted D07 projection blob `9123b5...` while the branch still contained predecessor `149816...`. W5 repaired the existing #467 lineage by converging that exact accepted Product blob from #441 without changing chess rules or weakening owner locks. Immediate gate is exact-head Formats run `34188684000` on #467@`d135f517...`. If terminal GREEN, selectively intake #467 into the same #441/#435 authority, rerun broad convergence, then ancestry/collision-review #536 and #560 for bounded intake. Keep #448, #491/#532, #498, #488, #510/#515/#541, #518, #562/#555, #478 and #511/#565/#558/#530 under exact-head watch. No second umbrella.

## Codex Cloud / Work
Codex Cloud: safest useful package is independent ancestry/collision review for selective #467 intake into #441 once exact-head Formats is GREEN, followed by #536/#560 convergence review. Do not implement another owner-lock, external-review, Library->PGN, frozen-blob or package-validator owner.

Work: verify end-to-end user-journey compatibility across corrected #467, terminal #536, #543/#560 and current #441 without editing reserved Product surfaces; distinguish stale ancestry/topology CI failures from real Product failures.

## Hard boundaries
- One canonical chess core; no chess rules in PGN/ChessBase/books/database/UI/Web adapters.
- No duplicate umbrella/convergence implementation.
- No package from stale #464/#466 lineage.
- No reuse of rejected Windows ZIPs.
- `NVDA_VERIFIED=NO` until Oleksii personally tests the exact fresh candidate.
- No paid services/compute without explicit owner approval.
- No silent invention/drop of source data.
- No raw local paths, tracebacks, provider internals or arbitrary adapter exception text in user-facing output.

## Windows/package/NVDA readiness truth
- Real V2 Windows composition exists, but no fresh final release candidate is accepted.
- Current #441 Windows Composition/UI Semantic/D01/data automation is GREEN; #567 fixed the Windows frozen-blob checkout failure.
- Broad Formats convergence is now validating corrected #467@`d135f517...`; its predecessor run failed only because Product blob and expected owner lock were inconsistent before Product tests.
- #536 external-review/live-state isolation is terminal GREEN and PROMOTE-ready after Formats convergence.
- #551 terminal Library-import UI wakeup recovery is merged.
- #543 Book->Board and #560 Library->PGN accessibility packages are terminal GREEN and PROMOTE-ready for bounded convergence.
- Current data, Book transaction, language, security/privacy and package successors are not fully converged.
- Required-resource preflight repair remains #565; #558/#530 remain payload/assembler layers.
- Old runtime/package authority #464/#466/#480 remains stale.
- No fresh final Windows ZIP is accepted in this epoch.
- Automated UIA/accessibility evidence does not equal human NVDA acceptance.
- `NVDA_VERIFIED=NO`.

## Next audit trigger
Audit immediately when #467@`d135f517...` terminalizes or is intaken into #441; broad #441 Formats becomes GREEN/RED on Product tests; #448 terminalizes; #491/#532, #518, #565/#558/#530, #562/#555/#478 become intakeable; selective intake of #536 or #560 occurs; a fresh runtime-data recomposition or Windows candidate appears; or ownership collides/stales again. Otherwise continue highest-priority disjoint integration work after a fresh collision scan.