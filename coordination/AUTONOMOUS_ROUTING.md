# Accessible Chess — Autonomous Routing Control

EPOCH: CHESS-2026-09-07-06
STATE: ACTIVE — FIVE HOURLY WORKERS

## Operating invariant
Every worker, Codex Cloud run and Work run must reconstruct the newest repository/PR/CI/runtime state before substantive work. Prefer exact current evidence over narrative history. Classify inherited targets as KEEP, CHANGE, STOP_STALE, COLLISION or PROMOTE. Do not duplicate active ownership.

## Product priority
Converge Version 2 formats/library/books/workflows into one genuinely usable Windows/NVDA release candidate without violating Stage 1 accessibility/release boundaries.

Canonical dependency order:
GameTree/PGN -> ACSDB/Library -> ChessBase adapters -> Books/Training -> later Teacher/Classroom/Web.

## Major change since prior epoch
- #435 remains the only formats umbrella/convergence authority at `9ac0600bf9d270e02334df1657c1ccc941f909b5`, but its exact broad Formats run is now terminal RED while Windows Composition, D01 PGN, D01 Books/Training and UI Semantic are GREEN. Treat the broad RED as an integration-gate blocker, not evidence that those Product surfaces regressed.
- #467 is the current bounded owner-lock convergence repair for that broad Formats gate. Its exact CI is queued; do not bypass it by weakening locks.
- #461 merged into the #441 runtime lineage and repaired the D01 PGN gate topology without Product mutation. #441 advanced to `40e1ef2184177600bcc88911529b718adde65df9`; its current full CI wave is queued.
- #448 advanced again to current head `503014c85e8839e8f5fe7a598ce75adc21123e1e` with source-presence/publication hardening. Its exact V1 Runtime Bridge CI is queued.
- #464 consumed an obsolete #448 snapshot and is therefore STOP_STALE as release authority until recomposed from terminal current #448.
- #466 was merged into the stale #464 stack. Its package-preflight owner bytes remain useful, but the combined runtime/package candidate MUST NOT be packaged or promoted as release-ready. Recompose only after current #448 terminalizes and #464 is refreshed.
- #480 addresses a proven Windows worktree byte-materialization false RED in the composition gate only; exact CI is queued.
- #469 and stacked #475 are W5 runtime lifecycle/PGN real-board Product repairs with exact Windows Composition CI queued. Do not duplicate their scopes.
- #473 remains evidence-only for the single-language defect; #482 is the current Product successor for that defect. Do not create a second language implementation.
- #479 and #481 are evidence-only Work findings for Book->real-board projection and startup cleanup. Product repairs belong to explicit runtime successors, not to duplicate evidence branches.

## Completed / DO NOT REPEAT
- #436 canonical bounded PGN ingress for BookTraining.
- #437 dirty-PGN open/discard guard.
- #438 V2 UI semantic/accessibility CI expansion.
- #439 Windows file-workflow action dispatch UI-thread fail-closed repair.
- #443 owner-bound dirty-PGN discard confirmation.
- #457 canonical package-preflight Windows superscript-device-alias repair is merged in its owner lineage.
- #461 D01 PGN convergence-aware CI topology repair is merged into #441.
- convergence-aware Books/Windows/PGN topology repairs already present on #435/#441.

## STOP_STALE / superseded
- #434 predecessor umbrella; #435 is successor.
- #440 old W4 convergence child.
- #442 old W4 QA child.
- #445 stale W4 accessibility/package-QA snapshot.
- #446 closed empty W4 attempt.
- #450 older W2 V1 executable-data bridge.
- #453 partial duplicate of the D07 lock repair.
- #465 and #477 duplicate D01 topology repairs; #461 is canonical.
- #464 as current release authority until recomposed from terminal latest #448.
- #466 as combined release candidate because it inherits stale #464. Preserve its package-preflight bytes for later recomposition; do not package from it.

## Active reservations / collision boundaries
- #441 owns Version2Application, runtime/release bootstrap, actual Windows composition and the shared runtime application boundary. Current head `40e1ef2184177600bcc88911529b718adde65df9`; CI queued. Do not directly rewrite this moving branch from another worker.
- #444 owns canonical PGN nested-comment lexical/resource-preflight work in `acs/pgn_roundtrip.py`.
- #447 owns the separate canonical nested-comment game-framing residual in `acs/gametree.py`.
- #448 owns the current shipped-V1 executable-local data bridge and must terminalize before any new runtime-data release intake.
- #454 owns the remaining one-line D07 Library Web owner-lock refresh; its broad Formats CI is still running.
- #467 owns the wider accepted-owner-package Formats lock convergence for #435; do not create another broad owner-lock table repair.
- #462 owns current W4 V2 focus/landmark/empty-state accessibility hardening; CI pending. `NVDA_VERIFIED=NO`.
- #469 owns native dirty-PGN close guard; #475 stacks the PGN->real-board projector on it. Do not duplicate either runtime Product path.
- #482 owns the single persisted language Product repair proved by #473.
- #476/#481 concern startup cleanup; avoid parallel runtime cleanup implementations until ownership is reconciled.
- #455/#472 and #458/#460/#463/#470 own bounded D04 security/convergence scopes; integrate only after exact-head evidence and dependency review.
- #468 owns Training progress crash recovery but currently has a security review blocker around opened-object identity; not intakeable yet.
- #478 owns current-base Library source/provenance catalog convergence; CI must terminalize before intake.

## Current release gates
1. #467 must prove the broad Formats owner-lock convergence GREEN on exact head; #435's current broad Formats RED is not acceptable release evidence by itself.
2. #441 current exact head must terminalize after #461 intake across Windows Composition, D01 PGN, Formats, UI Semantic and upgrade gates.
3. #448 current exact head must terminalize. Only then recompose #464 from the exact accepted owner bytes and subsequently recompose package-preflight intake; do not package from stale #464/#466.
4. #454 must terminalize; if #467 subsumes its exact lock lawfully, reconcile rather than duplicate.
5. #469/#475 must terminalize in stack order before PGN runtime projection can enter the release candidate.
6. #482 must terminalize before the release can claim one persisted runtime language across Stage1/V2.
7. #462 must terminalize before fresh Windows accessibility/package QA. Automated evidence is not human NVDA acceptance.
8. W1 #444/#447 and relevant D04 convergence/security children must terminalize and be reconciled in dependency order.
9. W2 #468/#478 and current #448 must pass their owner/security gates before selective intake.
10. Produce one fresh Windows candidate/package only from the refreshed, non-stale stack and obtain exact-machine packaged runtime evidence. Never reuse a rejected ZIP.
11. Human NVDA acceptance remains open. `NVDA_VERIFIED=NO` until Oleksii personally tests the exact fresh candidate.
12. ChessBase-family capability truth remains explicit SUPPORTED/PARTIAL/UNSUPPORTED/BLOCKED; unsupported formats must not hold the desktop release hostage.

## Worker routing
### W1 — Formats / GameTree / interoperability
KEEP. Finish #444/#447 and D04 isolated/security evidence without collapsing distinct ownership. Prefer terminal exact evidence and current-base convergence, not new duplicate parsers.

### W2 — Library / database / books / training content
PROMOTE current #448 as the data-release dependency. #468 remains blocked on security review; #478 is a current-base source-catalog convergence candidate pending CI. Avoid #441 runtime composition and W4 accessibility surfaces.

### W3 — User workflows / desktop composition
KEEP evidence/review role around current #441. #473 evidence is now consumed by #482 ownership. #471 is consumed by #475 ownership. Prefer new disjoint user-journey evidence such as Book projection/startup cleanup only when no Product owner already exists.

### W4 — Windows / NVDA / accessibility / package QA
PROMOTE #462 as the one current accessibility successor. Await terminal CI. After stable runtime/data stack exists, build one fresh candidate and exact-machine QA; never reuse rejected packages and never claim human NVDA verification.

### W5 — Integration / release / coordination
PROMOTE. Immediate job is dependency hygiene and convergence: keep #467/#454/#441/#448/#480/#469/#475/#482 under exact-head watch; mark stale stacks explicitly; intake only terminal verified packages in dependency order. Do not create a second umbrella.

## Codex Cloud / Work
Codex Cloud: safe work is a bounded exact-head release/integration repair that does not touch #441/#448/#462/#467/#469/#475/#482 owner surfaces. Prefer CI/evidence topology or a disjoint current-base integration blocker.

Work: useful work is independent exact-head release/user-journey evidence on gaps not already owned, especially Book->real-board and startup/cleanup behavior. Evidence branches must not mutate reserved Product surfaces.

## Hard boundaries
- One canonical chess core; no chess rules inside PGN/ChessBase/books/database/UI/Web adapters.
- No duplicate umbrella/convergence implementation.
- No package from stale #464/#466 stack.
- No reuse of rejected Windows ZIPs.
- `NVDA_VERIFIED=NO` until Oleksii personally tests the exact fresh candidate.
- No paid services/compute without explicit owner approval.
- No silent invention/drop of source data.

## Windows/package/NVDA readiness truth
- Real V2 Windows composition exists, but the current #441 exact head and stacked runtime fixes are not terminally proven yet.
- The old runtime/package stack is explicitly stale because its #448 dependency moved after intake.
- No fresh final Windows ZIP is accepted in this epoch.
- W4 #462 is the current accessibility hardening candidate; CI pending.
- Automated accessibility/semantic CI does not equal human NVDA acceptance.
- `NVDA_VERIFIED=NO`.

## Next audit trigger
Audit immediately when any of these occurs: #467 terminal GREEN/RED; #441 current wave terminalizes; #448 terminalizes; #454 terminalizes; #469/#475 or #482 terminalize; #462 terminalizes; stale #464 is recomposed from current #448; a fresh Windows candidate appears; a major security child becomes intakeable; ownership collides/stales again. Otherwise perform the next broader audit after the current worker wave or roughly six hours from this checkpoint.
