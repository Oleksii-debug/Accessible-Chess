# Accessible Chess — Autonomous Routing Control

EPOCH: CHESS-2026-09-08-10
STATE: ACTIVE — FIVE HOURLY WORKERS + WORK COMPLETION OWNER

## Operating invariant
Every worker, Codex Cloud run and Work run must reconstruct the newest repository/PR/CI/runtime state before substantive work. Prefer exact current evidence over narrative history. Classify inherited targets as KEEP, CHANGE, STOP_STALE, COLLISION or PROMOTE. Do not duplicate active ownership.

## Product priority
Converge Version 2 formats/library/books/workflows into one genuinely usable Windows/NVDA release candidate without violating Stage 1 accessibility/release boundaries.

Canonical dependency order:
GameTree/PGN -> ACSDB/Library -> ChessBase adapters -> Books/Training -> later Teacher/Classroom/Web.

## Live convergence snapshot — 2026-09-07 23:52Z
- #435 remains the single formats umbrella/convergence authority. Do not create a second umbrella.
- #441 remains the current V2 runtime/application authority, but is not yet final release authority while data/formats/security/runtime successors are pending.
- #444 and #447 are now merged/terminal and are DO-NOT-REPEAT.
- #448 remains the shipped-V1 executable-local data bridge and must terminalize before a fresh runtime-data candidate is composed.
- #536 remains the single live P0 external-review isolation Product owner. Static inspection still confirms one missing early guard in `retry_engine_move()` before `session.resume()`/engine side effects. #561 is evidence-only, but its current dual-OS harness is broken because it references the wrong prerequisite test module; therefore classify #561 as EVIDENCE_HARNESS_BROKEN, not valid hosted RED. The Product gap itself remains real and must be repaired in #536/current explicit successor only.
- #543 is now terminal-green current Book->Board repaint/focus-order baseline. #560 is the only live Library->PGN visible-route successor stacked on that green baseline and is awaiting exact-head terminal CI. #552/#557 remain STOP_STALE/evidence only.
- Reciprocal supersession temporarily left both terminal-import wakeup candidates closed. W5 arbitration reopens #551 as the canonical owner; #556 remains CLOSED duplicate/evidence only. #551 must obtain exact-head GREEN before intake.
- #565 remains the current required-resource preflight Product repair on immutable #538 RED parent. #511 remains restored preflight lineage; #558 payload preparation and #530 assembler remain separate bounded layers. None is release authority alone.
- #562 remains bounded D06 resume-lock TOCTOU owner; no temporary apply workflow may remain at intake.
- #555 remains bounded D07 complete filtered-export streaming owner; D06 remains sole PGN serializer.
- #518 remains Book progress/open transaction atomicity owner and has absorbed #545 shutdown cleanup evidence; #563/#564 are duplicate STOP_STALE.
- #491 remains persisted-language Product owner; #532 is downstream native-dialog localization.
- #510/#515 remain Markdown/HTML semantic list owners; #541 remains bounded EPUB semantic ingress.
- #488 remains ImportRegistry path-privacy owner.
- #478 remains current-base Library source/provenance convergence and is retesting after restoring its required #399 dedupe dependency.

## Completed / DO NOT REPEAT
- #436 canonical bounded PGN ingress for BookTraining.
- #437 dirty-PGN open/discard guard.
- #438 V2 UI semantic/accessibility CI expansion.
- #439 Windows file-workflow action dispatch UI-thread fail-closed repair.
- #443 owner-bound dirty-PGN discard confirmation.
- #444 canonical PGN nested-comment lexical/resource-preflight work.
- #447 nested-comment game-framing residual.
- #457 package-preflight Windows superscript-device-alias repair.
- #461 D01 PGN convergence-aware CI topology repair merged into #441.
- convergence-aware Books/Windows/PGN topology repairs already present on #435/#441.

## STOP_STALE / superseded / collision decisions
- #434 predecessor umbrella; #435 is successor.
- #440/#442/#445/#446 old W4 snapshots/attempts.
- #450 older V1 executable-data bridge; #448 is current.
- #453 partial duplicate of D07 lock repair.
- #465/#477 duplicate D01 topology repairs; #461 is canonical.
- #464/#466/#480 stale runtime/package ancestry. Never package from these.
- #482/#483/#485/#486/#487/#489 stale or duplicate language implementations; #491 is canonical.
- #496/#499 duplicate Book-board implementations.
- #512 duplicate HTML-list implementation; #515 is canonical.
- #535/#542/#554 closed external-review predecessors; #536 is current Product owner.
- #546/#566 are stale/evidence-only external-review branches.
- #559 stale review-engine evidence; #561 is current evidence-only but harness-broken.
- #552/#557 closed Library->PGN predecessors; #560 is current.
- #538 is RED-parent/evidence lineage; #565 is current required-resource Product repair.
- #556 remains duplicate/evidence only; #551 is reopened canonical terminal-import wakeup owner.
- #563/#564 are duplicates of #518.

## Active reservations / collision boundaries
- #441 owns Version2Application, runtime/release bootstrap, actual Windows composition and shared application boundary.
- #448 owns shipped-V1 executable-local data bridge.
- #454 owns bounded D07 Library Web owner-lock refresh unless accepted #467 evidence explicitly subsumes it.
- #467 owns broad Formats accepted-owner-package lock convergence.
- #469/#475/#495 remain PGN/Book projection ancestry; #536 owns the current P0 external-review isolation Product repair; #561 is evidence only.
- #543 owns accepted Book->Board ordered Stage1 repaint/focus baseline; #560 owns only direct Library->PGN route refresh on top.
- #491 owns one persisted language; #532 owns downstream trusted native-dialog localization.
- #498 owns composition-root startup cleanup.
- #510 owns Markdown semantic lists; #515 owns HTML semantic lists; #541 owns bounded EPUB semantic ingress.
- #518 owns Book application progress/open command atomicity; #526/#545 evidence only.
- #551 owns terminal Library-import UI wakeup self-recovery in the existing Windows host; #556 must not be intaken separately.
- #488 owns ImportRegistry path privacy.
- #511 owns restored current-base V2 preflight; #565 owns required-resource Product hardening; #558 owns prepared release payload staging; #530 owns assembler.
- #562 owns only D06 resume-lock validation/open identity TOCTOU.
- #555 owns only D07 lazy complete filtered export; D06 stays sole PGN writer.
- #455/#472 and #458/#460/#463/#470 own bounded D04 security/convergence scopes; integrate only after exact-head evidence and dependency review.
- #468 owns Training progress crash recovery but remains blocked on opened-object identity/security review.
- #478 owns current-base Library source/provenance catalog convergence.

## Current release gates
1. P0 external review: repair `retry_engine_move()` inside #536/current explicit successor before any refreshed candidate intake; fix #561 evidence harness or absorb an equivalent exact regression, then require exact-head dual-OS GREEN.
2. #467 must terminalize GREEN on exact current head or expose a real blocker; broad owner locks must not be weakened.
3. #441 must be reconciled with terminal current data/formats/runtime successors rather than promoted from historical evidence alone.
4. #448 must terminalize before one fresh runtime-data recomposition is created. Never revive #464/#466.
5. #454 must terminalize or be explicitly superseded by accepted #467 evidence.
6. #491 then #532 must terminalize in dependency order before claiming one persisted/localized Windows language experience.
7. #498 must close startup cleanup without creating a second runtime owner.
8. #510/#515 and selectively accepted #541 must terminalize before broader Books ingestion claims are promoted.
9. #518 must terminalize before Book progress/open transactions are considered durable.
10. #551 must terminalize GREEN before Library import completion is considered visibly self-recovering.
11. #488 plus relevant D04 security/privacy children, including #562 where applicable, must terminalize before release intake.
12. #543 is accepted baseline; #560 must terminalize before fresh Windows accessibility/package QA.
13. #555 may be selectively intaken only after exact-head dual-OS and collision review; it must not change D06 serialization authority.
14. V2 package path must converge through existing chain: #511 -> #565 plus #558 -> #530, with exact packaged-runtime evidence. No rejected ZIP may be reused.
15. Produce exactly one fresh Windows candidate/package from the refreshed non-stale stack only.
16. Human NVDA acceptance remains open. `NVDA_VERIFIED=NO` until Oleksii personally tests that exact fresh candidate.
17. ChessBase-family capability truth remains explicit SUPPORTED/PARTIAL/UNSUPPORTED/BLOCKED; unsupported adapters must not hold unrelated desktop release work hostage.

## Worker routing
### W1 — Formats / GameTree / interoperability
CHANGE. #444/#447 are complete and DO-NOT-REPEAT. Continue disjoint current owners such as #547 bounded PGN model materialization and #562 resume-lock TOCTOU only after exact-head evidence; do not duplicate #467 or D07 work.

### W2 — Library / database / books / training content
PROMOTE dependency-safe work only. #448 is the data-release dependency. #518 owns Book progress transactions; #510/#515 own Markdown/HTML; #541 owns EPUB ingress; #555 owns complete filtered Library export streaming; #478 owns source/provenance convergence. Keep #468 blocked until identity/security is resolved.

### W3 — User workflows / desktop composition
CHANGE toward review/integration of current #441 descendants. Highest-value current Product gap remains #536 retry-engine guard, but do not create another owner. Validate/fix evidence and route repair to #536. Do not duplicate #491/#532, #551, #518 or W4 #543/#560.

### W4 — Windows / NVDA / accessibility / package QA
PROMOTE #543 as accepted Book->Board baseline and finish #560 exact-head Library->PGN route evidence. After P0/data/security/runtime stack is stable, build one fresh candidate and exact-machine QA. Never reuse rejected packages and never claim human NVDA verification.

### W5 — Integration / release / coordination
PROMOTE. Immediate job is dependency convergence and ownership cleanup: keep #536/#561, #467/#454, #441/#448, #491/#532, #498, #488, #510/#515/#541, #518/#551, #543/#560, #562/#555, #478 and the #511/#565/#558/#530 package chain under exact-head watch. Keep stale package ancestry and duplicate owners out of release authority. Do not create a second umbrella.

## Codex Cloud / Work
Codex Cloud: safest current package is bounded exact-head evidence/CI topology that does not touch reserved Product surfaces. Highest-value immediate task is repair of #561's evidence harness against current #536 or independent package-chain collision review; do not implement another external-review or package validator owner.

Work: verify user-journey/release evidence where no Product owner exists, especially cross-package compatibility after P0/data/runtime gates turn green. Do not duplicate #536, #518, #551, #543/#560, #491/#532, #565/#558/#530 or #562/#555.

## Hard boundaries
- One canonical chess core; no chess rules inside PGN/ChessBase/books/database/UI/Web adapters.
- No duplicate umbrella/convergence implementation.
- No package from stale #464/#466 lineage.
- No reuse of rejected Windows ZIPs.
- `NVDA_VERIFIED=NO` until Oleksii personally tests the exact fresh candidate.
- No paid services/compute without explicit owner approval.
- No silent invention/drop of source data.
- No raw local paths, tracebacks, provider internals or arbitrary adapter exception text in user-facing output.

## Windows/package/NVDA readiness truth
- Real V2 Windows composition exists, but a fresh final release candidate is NOT accepted.
- P0 external-review/live-state isolation remains not intakeable: static Product inspection confirms `retry_engine_move()` still lacks the early external-review guard. #561's current hosted evidence harness is broken and must not be cited as valid RED until repaired.
- #543 Book->Board repaint/focus baseline is terminal-green; #560 is the remaining current W4 Library->PGN successor under exact-head CI.
- Terminal Library-import UI wakeup ownership is restored to one live owner, #551, but exact-head GREEN is still required.
- Current data, Book transaction, language, security/privacy and package successors are not fully converged.
- Required-resource preflight repair is #565; #538 is only its RED parent. Payload preparation #558 and assembler #530 remain separate layers.
- Old runtime/package authority #464/#466/#480 remains stale.
- No fresh final Windows ZIP is accepted in this epoch.
- Automated accessibility/semantic/UIA evidence does not equal human NVDA acceptance.
- `NVDA_VERIFIED=NO`.

## Next audit trigger
Audit immediately when any of these occurs: #536 repairs retry and exact evidence terminalizes; #561 harness becomes valid; #467 terminalizes; #448 terminalizes; #454 is accepted/superseded; #491/#532 terminalize; #518 terminalizes; #551 terminalizes; #560 terminalizes; #565/#558/#530 package chain terminalizes; #562/#555/#478 becomes intakeable; a fresh runtime-data recomposition appears; a fresh Windows candidate appears; or ownership collides/stales again. Otherwise continue highest-priority disjoint integration work after a fresh collision scan.
