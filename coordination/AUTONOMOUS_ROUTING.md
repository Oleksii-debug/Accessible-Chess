# Accessible Chess — Autonomous Routing Control

EPOCH: CHESS-2026-09-08-09
STATE: ACTIVE — FIVE HOURLY WORKERS + WORK COMPLETION OWNER

## Operating invariant
Every worker, Codex Cloud run and Work run must reconstruct the newest repository/PR/CI/runtime state before substantive work. Prefer exact current evidence over narrative history. Classify inherited targets as KEEP, CHANGE, STOP_STALE, COLLISION or PROMOTE. Do not duplicate active ownership.

## Product priority
Converge Version 2 formats/library/books/workflows into one genuinely usable Windows/NVDA release candidate without violating Stage 1 accessibility/release boundaries.

Canonical dependency order:
GameTree/PGN -> ACSDB/Library -> ChessBase adapters -> Books/Training -> later Teacher/Classroom/Web.

## Live convergence snapshot — 2026-09-07 22:10Z
- #435 remains the single formats umbrella/convergence authority. Do not create a second umbrella.
- #441 remains the current V2 runtime/application authority. Historical green evidence remains useful, but it is not release authority while current data/formats/security/runtime successors are pending.
- #448 remains the shipped-V1 executable-local data bridge and must terminalize before a fresh runtime-data candidate is composed.
- Major P0 ownership changed: #554 is CLOSED and must be STOP_STALE. #536 is again the live external-review isolation Product owner. Its current exact head has a successful Windows Composition run, but #561 proves one remaining P0 mutation path: `retry_engine_move()` can resume the live engine session during PGN/Book review because #536 lacks the same early external-review guard used by its other engine commands. Therefore #536 is PROMOTE-AS-CANONICAL-BUT-NOT-INTAKEABLE until that exact oracle is absorbed into #536/current successor and exact-head dual-OS evidence is green.
- #561 is RED-first evidence-only and must not become a competing Product owner.
- #543 remains the W4 Book->Board repaint/focus-order successor. #552 is CLOSED superseded. #560 is now the single current Library->PGN visible-route refresh owner stacked on #543; keep #552/#557 evidence-only.
- #538 is no longer the terminal Product hardening target. #565 is the current atomic Product repair on the immutable #538 RED parent for required WebView/Stockfish/sounds/GPL source/notices preflight. #511 remains the restored preflight lineage; #530 remains assembler; #558 is a distinct payload-preparation layer. None are release authority and none produce an accepted ZIP.
- #562 is a new bounded D06 security owner for resume-lock validation/open TOCTOU. Keep it isolated from parser/Library/runtime work; no temporary apply workflow may remain at intake.
- #555 is a new bounded D07 Library filtered-export streaming owner. Preserve D06 as sole PGN serializer and require exact-head dual-OS before intake.
- #518 remains Book progress/open transaction atomicity owner; #526/#545 remain evidence only.
- #491 remains persisted-language Product owner; #532 remains downstream native-dialog localization.
- #510/#515 remain Markdown/HTML semantic list owners; #541 remains bounded EPUB semantic ingress.
- #488 remains ImportRegistry path-privacy owner.

## Completed / DO NOT REPEAT
- #436 canonical bounded PGN ingress for BookTraining.
- #437 dirty-PGN open/discard guard.
- #438 V2 UI semantic/accessibility CI expansion.
- #439 Windows file-workflow action dispatch UI-thread fail-closed repair.
- #443 owner-bound dirty-PGN discard confirmation.
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
- #535/#542/#554 are closed external-review convergence predecessors. #536 is current Product owner.
- #546 remains duplicate/evidence-only for the external-review defect.
- #552/#557 are closed Library->PGN route-refresh predecessors; #560 is current.
- #538 is RED-parent/evidence lineage for required package resources; #565 is current Product repair.

## Active reservations / collision boundaries
- #441 owns Version2Application, runtime/release bootstrap, actual Windows composition and shared application boundary.
- #444 owns canonical PGN nested-comment lexical/resource-preflight work; #447 owns the distinct nested-comment game-framing residual.
- #448 owns shipped-V1 executable-local data bridge.
- #454 owns bounded D07 Library Web owner-lock refresh unless accepted #467 exact-head evidence explicitly subsumes it.
- #467 owns broad Formats accepted-owner-package lock convergence.
- #469/#475 and #495 remain PGN/Book projection ancestry; #536 owns the current P0 external-review isolation Product repair. #561 is evidence only.
- #543 owns Book->Board ordered Stage1 repaint/focus successor; #560 owns only direct Library->PGN route refresh on top of that behavior.
- #491 owns one persisted language; #532 owns only downstream trusted native-dialog localization.
- #498 owns composition-root startup cleanup.
- #510 owns Markdown semantic lists; #515 owns HTML semantic lists; #541 owns bounded EPUB semantic ingress.
- #518 owns Book application progress/open command atomicity; #526/#545 are evidence only.
- #551 owns terminal Library-import UI wakeup self-recovery in the existing Windows host.
- #488 owns ImportRegistry path privacy.
- #511 owns restored current-base V2 preflight; #565 owns current required-resource Product hardening; #530 owns assembler; #558 owns prepared release payload staging. Do not collapse them into a second release authority.
- #562 owns only D06 resume-lock validation/open identity TOCTOU.
- #555 owns only D07 lazy complete filtered export; D06 stays sole PGN writer.
- #455/#472 and #458/#460/#463/#470 own bounded D04 security/convergence scopes; integrate only after exact-head evidence and dependency review.
- #468 owns Training progress crash recovery but remains blocked on opened-object identity/security review.
- #478 owns current-base Library source/provenance catalog convergence.

## Current release gates
1. P0 external review: #536 must absorb #561's retry-engine side-effect oracle (or be replaced by one explicit successor) and terminalize GREEN on exact head before any refreshed release candidate intake.
2. #467 must terminalize GREEN on exact current head or expose a real blocker; broad owner locks must not be weakened.
3. #441 must be reconciled with terminal current data/formats/runtime successors rather than promoted from historical partial-green evidence alone.
4. #448 must terminalize before one fresh runtime-data recomposition is created. Never revive #464/#466.
5. #454 must terminalize or be explicitly superseded by accepted #467 evidence.
6. #491 then #532 must terminalize in dependency order before claiming one persisted/localized Windows language experience.
7. #498 must close startup cleanup without creating a second runtime owner.
8. #510/#515 and selectively accepted #541 must terminalize before broader Books ingestion claims are promoted.
9. #518 must terminalize before Book progress/open transactions are considered durable.
10. #551 must terminalize before Library import completion is considered visibly reliable.
11. #488 plus relevant D04 security/privacy children, including isolated intake review of #562 where applicable, must terminalize before release intake.
12. #543 and #560 must terminalize before fresh Windows accessibility/package QA. Do not revive #552.
13. #555 may be selectively intaken only after exact-head dual-OS and collision review; it must not change D06 serialization authority.
14. V2 package path must converge through the existing preflight/payload/assembler chain: #511 -> #565 plus #558 -> #530, with exact packaged-runtime evidence. No rejected ZIP may be reused.
15. Produce exactly one fresh Windows candidate/package from the refreshed non-stale stack only.
16. Human NVDA acceptance remains open. `NVDA_VERIFIED=NO` until Oleksii personally tests that exact fresh candidate.
17. ChessBase-family capability truth remains explicit SUPPORTED/PARTIAL/UNSUPPORTED/BLOCKED; unsupported adapters must not hold unrelated desktop release work hostage.

## Worker routing
### W1 — Formats / GameTree / interoperability
KEEP. Finish #444/#447 and isolated D04/security evidence. #547 remains bounded PGN model materialization ownership if its temporary apply workflow is removed and exact Product repair/dual-OS CI become valid. #562 is disjoint D06 lock TOCTOU ownership; do not duplicate it.

### W2 — Library / database / books / training content
PROMOTE dependency-safe work only. #448 is the data-release dependency. #518 owns Book progress transactions; #510/#515 own Markdown/HTML and #541 owns EPUB ingress. #555 owns complete filtered Library export streaming. Keep #468 blocked until identity/security is resolved and #478 within its existing owner.

### W3 — User workflows / desktop composition
CHANGE toward review/integration of current #441 descendants. Do not duplicate #536 P0 review isolation, #491/#532 language, #551 import wakeup, #518 Book transactions or W4 #543/#560 visible-state successors.

### W4 — Windows / NVDA / accessibility / package QA
PROMOTE #543 Book->Board ordered repaint plus #560 direct Library->PGN route refresh as current successors to #462 baseline. After P0/data/security/runtime stack is stable, build one fresh candidate and exact-machine QA. Never reuse rejected packages and never claim human NVDA verification.

### W5 — Integration / release / coordination
PROMOTE. Immediate job is dependency convergence: keep #536/#561, #467/#454, #441/#448, #491/#532, #498, #488, #510/#515/#541, #518/#551, #543/#560, #562/#555 and the #511/#565/#558/#530 package chain under exact-head watch. Keep #554/#552/#538-as-terminal-target and stale package ancestry out of release authority. Do not create a second umbrella.

## Codex Cloud / Work
Codex Cloud: safest package is bounded exact-head release/integration evidence or CI topology that does not touch currently reserved Product surfaces. Highest-value current options are independent collision review of the #511/#565/#558/#530 package chain, or exact-head evidence around #536 after the #561 oracle is absorbed. Do not implement another external-review or package validator owner.

Work: verify current user-journey/release evidence where no Product owner exists, especially cross-package compatibility after P0/data/runtime gates turn green. Do not duplicate #536, #518, #551, #543/#560, #491/#532, #565/#558/#530 or #562/#555 ownership.

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
- P0 external-review/live-state isolation is not yet intakeable because #561 proves the current #536 head still leaves engine retry side effects reachable during external review, despite successful Windows Composition evidence on that head.
- Current import-host, Book transaction, language, security/privacy and packaging successors are not fully converged.
- #543/#560 are the current W4 visible-state successor chain; #552 is stale.
- Required-resource preflight repair is now #565; #538 is only its RED parent. Payload preparation #558 and assembler #530 remain separate layers.
- Old runtime/package authority #464/#466/#480 remains stale.
- No fresh final Windows ZIP is accepted in this epoch.
- Automated accessibility/semantic/UIA evidence does not equal human NVDA acceptance.
- `NVDA_VERIFIED=NO`.

## Next audit trigger
Audit immediately when any of these occurs: #536 absorbs/resolves #561 and terminalizes; #467 terminalizes; #448 terminalizes; #454 is accepted/superseded; #491/#532 terminalize; #518 terminalizes; #551 terminalizes; #543/#560 terminalize; #565/#558/#530 package chain terminalizes; #562 or #555 becomes intakeable; a fresh runtime-data recomposition appears; a fresh Windows candidate appears; or ownership collides/stales again. Otherwise continue highest-priority disjoint integration work after a fresh collision scan.
