# Accessible Chess — Autonomous Routing Control

EPOCH: CHESS-2026-09-08-12
STATE: ACTIVE — FIVE HOURLY WORKERS + WORK COMPLETION OWNER

## Operating invariant
Every worker, Codex Cloud and Work run must reconstruct newest repository/PR/CI/runtime truth before substantive work. Classify inherited targets KEEP, CHANGE, STOP_STALE, COLLISION or PROMOTE. Do not duplicate active ownership.

## Product priority
Converge Version 2 formats/library/books/workflows into one usable Windows/NVDA release candidate without violating Stage 1 release or accessibility boundaries.

Canonical dependency order: GameTree/PGN -> ACSDB/Library -> ChessBase adapters -> Books/Training -> later Teacher/Classroom/Web.

## Live convergence snapshot — 2026-09-08 01:48Z
- #435 remains the single formats umbrella/convergence authority. Do not create a second umbrella.
- #441 remains current V2 runtime/application authority; W5 has just merged terminal-green #551 into this lineage at `2f535d9`, and fresh #441 exact-head CI is queued. Do not promote #441 to final release authority until that CI and current data/formats/security/package successors are reconciled.
- #536 remains the sole P0 external-review isolation Product owner and is now **PROMOTE / TERMINAL GREEN** on exact head `2c981d3`: Accessible Chess Version 2 Windows Composition run 34175002517 completed SUCCESS. The early `retry_engine_move()` fail-closed guard is verified before inherited engine resume/side effects. Do not recreate the old defect, revive #561 as Product authority, or create a parallel owner. Selectively compose #536 into the single convergence lineage after ancestry/collision review.
- #561 remains evidence-only and is not release authority.
- #543 is terminal-green Book->Board repaint/focus baseline. #560 is terminal-green Library->PGN visible-route refresh on top of #543 and remains PROMOTE-ready for bounded selective intake; do not merge it blindly as a second umbrella.
- #551 is now COMPLETED/DO-NOT-REPEAT as a separate owner: exact-head Windows Composition was GREEN and W5 merged it into #441. Its one-retry terminal Library-import UI wakeup recovery now belongs to the runtime lineage. #556 remains closed duplicate/evidence only.
- #448 remains shipped-V1 executable-local data bridge and must terminalize before fresh runtime-data recomposition.
- #467 remains broad Formats accepted-owner-package lock convergence. #454 remains bounded D07 Library Web owner-lock refresh unless accepted #467 evidence explicitly subsumes it.
- #565 remains required-resource preflight Product repair on immutable #538 RED parent; #511 is restored preflight lineage, #558 payload preparation, #530 assembler. None alone is release authority.
- #562 owns bounded D06 resume-lock TOCTOU; no temporary apply workflow may remain at intake.
- #555 owns bounded D07 complete filtered-export streaming; D06 remains sole PGN serializer.
- #518 owns Book progress/open transaction atomicity; #563/#564 remain STOP_STALE duplicates.
- #491 owns persisted language; #532 is downstream native-dialog localization.
- #510/#515 own Markdown/HTML semantic lists; #541 owns bounded EPUB semantic ingress.
- #488 owns ImportRegistry path privacy.
- #478 owns current-base Library source/provenance convergence and is retesting its real-corpus path after restoring #399 dedupe dependency.

## Completed / DO NOT REPEAT
- #436 canonical bounded PGN ingress for BookTraining.
- #437 dirty-PGN open/discard guard.
- #438 V2 UI semantic/accessibility CI expansion.
- #439 Windows file-workflow UI-thread fail-closed repair.
- #443 owner-bound dirty-PGN discard confirmation.
- #444 canonical PGN nested-comment lexical/resource-preflight work.
- #447 nested-comment game-framing residual.
- #457 package-preflight Windows superscript-device-alias repair.
- #461 D01 PGN convergence-aware CI topology repair merged into #441.
- #543 Book->Board ordered Stage1 repaint/focus baseline.
- #551 terminal Library-import UI wakeup self-recovery, merged into #441 on this epoch.
- convergence-aware Books/Windows/PGN topology repairs already present on #435/#441.

## STOP_STALE / superseded / collision decisions
- #434 predecessor umbrella; #435 is successor.
- #440/#442/#445/#446 old W4 snapshots/attempts.
- #450 older V1 executable-data bridge; #448 is current.
- #453 partial duplicate of D07 lock repair.
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
- #454/#467 own their existing D07/formats lock scopes; do not weaken owner locks.
- #469/#475/#495 are PGN/Book projection ancestry; #536 owns the terminal-green P0 external-review Product delta awaiting selective convergence intake.
- #543/#560 own accepted Book->Board baseline and bounded Library->PGN route refresh respectively.
- #491/#532 own persisted language and native-dialog localization in dependency order.
- #498 owns composition-root startup cleanup.
- #510/#515/#541 own Markdown/HTML/EPUB semantic ingestion scopes.
- #518 owns Book progress/open command atomicity.
- #488 owns ImportRegistry path privacy.
- #511/#565/#558/#530 own existing package/preflight layers.
- #562 owns only D06 resume-lock validation/open identity TOCTOU.
- #555 owns only D07 lazy complete filtered export; D06 stays sole PGN writer.
- #455/#472 and #458/#460/#463/#470 remain bounded D04 security/convergence scopes.
- #468 Training progress crash recovery remains blocked on opened-object identity/security review.
- #478 owns current-base Library source/provenance catalog convergence.

## Current release gates
1. **P0 external review: PROMOTE #536.** Exact-head dual-OS Windows Composition run 34175002517 is terminal SUCCESS. Preserve the owner and selectively compose its bounded Product delta into the single convergence lineage after ancestry/collision review; do not create a successor merely because it is stacked.
2. **Runtime wakeup: COMPLETED #551.** W5 merged terminal-green #551 into #441. Fresh #441 exact-head workflows are now queued and must terminalize before the merged runtime state is promoted.
3. #467 must terminalize GREEN or expose a real blocker; broad owner locks must not be weakened.
4. #441 must be reconciled with terminal current data/formats/runtime successors, including selective intake of #536/#560, rather than promoted from historical evidence alone.
5. #448 must terminalize before one fresh runtime-data recomposition. Never revive #464/#466.
6. #454 must terminalize or be explicitly superseded by accepted #467 evidence.
7. #491 then #532 must terminalize before one persisted/localized Windows language experience is claimed.
8. #498 must close startup cleanup without creating a second runtime owner.
9. #510/#515 and selectively accepted #541 must terminalize before broader Books ingestion claims.
10. #518 must terminalize before Book progress/open transactions are considered durable.
11. #488 plus relevant D04 privacy/security children, including #562 where applicable, must terminalize before release intake.
12. #543/#560 are accepted/terminal-green accessibility packages; selectively compose #560 into the one convergence lineage after ancestry/collision review.
13. #555 may be intaken only after exact-head dual-OS and collision review and must not change D06 serialization authority.
14. Package path remains #511 -> #565 plus #558 -> #530 with exact packaged-runtime evidence. No rejected ZIP may be reused.
15. Produce exactly one fresh Windows candidate/package from the refreshed non-stale stack.
16. Human NVDA acceptance remains open: `NVDA_VERIFIED=NO` until Oleksii personally tests that exact candidate.
17. ChessBase-family capability truth remains SUPPORTED/PARTIAL/UNSUPPORTED/BLOCKED; unsupported adapters must not block unrelated desktop release work.

## Worker routing
### W1 — Formats / GameTree / interoperability
CHANGE. #444/#447 are complete. Continue disjoint owners such as #547 bounded model materialization and #562 resume-lock TOCTOU only after exact-head evidence. Do not duplicate #467/D07 work.

### W2 — Library / database / books / training content
PROMOTE dependency-safe work only. #448 is the data-release dependency. Continue #518, #510/#515/#541, #555 and #478 in their reserved scopes. Keep #468 blocked until identity/security is resolved.

### W3 — User workflows / desktop composition
CHANGE from P0 repair to convergence. #536 is terminal GREEN and must not be reimplemented. Review/selectively converge #536 into the current #441/#435 lineage without duplicating #491/#532, merged #551, #518 or W4 #543/#560.

### W4 — Windows / NVDA / accessibility / package QA
PROMOTE #543 and #560 as accepted terminal-green accessibility packages. Do not spawn another Library->PGN owner. After P0/data/security/runtime stack converges, build one fresh candidate and exact-machine QA. Never reuse rejected packages or claim human NVDA verification.

### W5 — Integration / release / coordination
PROMOTE. This epoch terminalized #536 as GREEN and merged terminal-green #551 into #441. Next immediate gate is fresh #441 exact-head CI on merged runtime head, followed by ancestry/collision review for bounded selective convergence of #536 and #560 into the one authority. Keep #467/#454, #448, #491/#532, #498, #488, #510/#515/#541, #518, #562/#555, #478 and #511/#565/#558/#530 under exact-head watch. No second umbrella.

## Codex Cloud / Work
Codex Cloud: safest useful package is independent ancestry/collision review for selective #536/#560 convergence into current #441/#435, or exact-head CI diagnostics if the new #441 run is RED. Do not implement another external-review, Library->PGN or package-validator owner.

Work: verify end-to-end user-journey compatibility across terminal #536, #543/#560 and the refreshed #441 runtime after #551 intake, without editing reserved Product surfaces.

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
- P0 external-review/live-state isolation #536 is now terminal GREEN on exact head after the retry-side-effect guard and regression-probe repair.
- #551 terminal Library-import UI wakeup recovery is GREEN and has been merged into #441; fresh merged-head workflows are queued, so runtime authority is not yet promoted.
- #543 Book->Board and #560 Library->PGN accessibility packages are terminal GREEN and PROMOTE-ready for bounded convergence.
- Current data, Book transaction, language, security/privacy and package successors are not fully converged.
- Required-resource preflight repair remains #565; #538 is evidence-only RED parent; #558/#530 remain separate payload/assembler layers.
- Old runtime/package authority #464/#466/#480 remains stale.
- No fresh final Windows ZIP is accepted in this epoch.
- Automated accessibility/UIA evidence does not equal human NVDA acceptance.
- `NVDA_VERIFIED=NO`.

## Next audit trigger
Audit immediately when fresh #441 head `2f535d9` terminalizes; #467/#448/#454 terminalizes; #491/#532, #518, #565/#558/#530, #562/#555/#478 become intakeable; selective intake of #536 or #560 occurs; a fresh runtime-data recomposition or Windows candidate appears; or ownership collides/stales again. Otherwise continue highest-priority disjoint integration work after a fresh collision scan.
