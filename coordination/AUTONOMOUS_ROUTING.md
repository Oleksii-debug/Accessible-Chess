# Accessible Chess — Autonomous Routing Control

EPOCH: CHESS-2026-09-07-07
STATE: ACTIVE — FIVE HOURLY WORKERS + WORK COMPLETION OWNER

## Operating invariant
Every worker, Codex Cloud run and Work run must reconstruct the newest repository/PR/CI/runtime state before substantive work. Prefer exact current evidence over narrative history. Classify inherited targets as KEEP, CHANGE, STOP_STALE, COLLISION or PROMOTE. Do not duplicate active ownership.

## Product priority
Converge Version 2 formats/library/books/workflows into one genuinely usable Windows/NVDA release candidate without violating Stage 1 accessibility/release boundaries.

Canonical dependency order:
GameTree/PGN -> ACSDB/Library -> ChessBase adapters -> Books/Training -> later Teacher/Classroom/Web.

## Live convergence snapshot — 2026-09-07 21:37Z
- #435 remains the formats umbrella/convergence authority at `9ac0600bf9d270e02334df1657c1ccc941f909b5`. Its broad Formats gate is RED because accepted-owner locks lagged current packages; do not reinterpret that as a regression in independently GREEN Product surfaces.
- #467 is the single bounded broad Formats owner-lock convergence repair at `2c0e141de72ec6b0fd1429cd198c4e09e211c144`. Exact run `34159417926` is in progress. Do not create another broad owner-lock repair.
- #441 is the current V2 runtime/application owner at `40e1ef2184177600bcc88911529b718adde65df9`. On that exact head Windows Composition `34160972077`, UI Semantic `34160971939`, and D01 PGN Workspace `34160971980` are GREEN; Data Upgrade Tracked Writer `34160971911`, Formats `34160971915`, and Data Upgrade V6 `34160971926` are still queued. Do not call the whole head terminal GREEN yet.
- #448 is the current shipped-V1 executable-local data bridge. Live head is `0d3abade48d788a1230179342816c38a884ff4e6`; exact V1 Runtime Bridge run `34162877502` is queued. This supersedes older routing references to `503014c...`.
- #464 is CLOSED STOP_STALE. #466 inherits stale #464 and is not release authority. #480 is CLOSED STOP_STALE_PARENT. Do not package from that stack.
- #469 -> #475 own dirty-PGN close/lifecycle and PGN->real-board projection. #495 is the single active Book->real-release-board successor at `31934608ed62f2485b5a17972f7536dac72e98e3`; #496 and #499 are closed duplicates. #479 remains evidence-only.
- #491 is the single current persisted-language Product owner at `1c7c96572eb73b15514ed3a92e03d268c7fe8e7c`, rooted directly on current #441 runtime. #482/#483/#485/#486/#487/#489 are stale/closed predecessors or duplicates and must not be revived.
- #498 owns the earlier composition-root startup resource-leak repair at `b41d1c6a8577bcb783e8538c11b9404014819d07`, stacked after #475. #476/#481 are evidence/predecessor paths; do not create another startup cleanup implementation.
- #515 is the canonical HTML semantic-list Product owner on current #441 base, head `756643cfcedd933af41145e200851931b9680a33`. A mutual-close race briefly left #512 and #515 both closed; Work resolved it by reopening #515 because it is current-runtime-rooted and already contains RED regression, Product repair and Linux/Windows gate. #512 remains CLOSED STOP_DUPLICATE. Exact #515 run `34163747603` is queued.
- #510 separately owns Markdown semantic-list preservation at current head `3373e46a07582c13cf72acd02c89a3a3ccd27c15`. Do not merge HTML and Markdown ownership.
- #488 owns ImportRegistry path-privacy restoration at the adapter boundary. This is a real privacy/error-surface repair; do not duplicate it in runtime/UI code.
- #462 remains the current W4 focus/landmark/empty-state accessibility hardening candidate. Automated accessibility evidence is not human NVDA acceptance.

## Completed / DO NOT REPEAT
- #436 canonical bounded PGN ingress for BookTraining.
- #437 dirty-PGN open/discard guard.
- #438 V2 UI semantic/accessibility CI expansion.
- #439 Windows file-workflow action dispatch UI-thread fail-closed repair.
- #443 owner-bound dirty-PGN discard confirmation.
- #457 canonical package-preflight Windows superscript-device-alias repair in its owner lineage.
- #461 D01 PGN convergence-aware CI topology repair merged into #441.
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
- #464 closed stale runtime-data intake; recompose only from terminal latest #448.
- #466 stale combined package candidate inherited from #464; preserve useful package-preflight evidence only.
- #480 closed stale-parent Windows child.
- #482/#483/#485/#486/#487/#489 stale or duplicate language implementations; #491 is canonical.
- #496/#499 duplicate Book real-board implementations; #495 is canonical.
- #512 duplicate HTML-list implementation; #515 is canonical.

## Active reservations / collision boundaries
- #441 owns `Version2Application`, runtime/release bootstrap, actual Windows composition and shared application boundary. Product successors may stack only through explicit ownership and exact-base discipline.
- #444 owns canonical PGN nested-comment lexical/resource-preflight work in `acs/pgn_roundtrip.py`.
- #447 owns the separate canonical nested-comment game-framing residual in `acs/gametree.py`.
- #448 owns current shipped-V1 executable-local data bridge.
- #454 owns the remaining D07 Library Web owner-lock refresh unless #467 terminal evidence lawfully subsumes it.
- #467 owns broad Formats accepted-owner-package lock convergence.
- #462 owns current W4 V2 focus/landmark/empty-state accessibility hardening.
- #469/#475 own PGN runtime lifecycle/real-board projection; #495 is the Book projection successor on that same projection authority.
- #491 owns one persisted language across Stage1/V2/runtime/native-menu/WebView presentation.
- #498 owns composition-root startup cleanup.
- #510 owns Markdown semantic lists; #515 owns HTML semantic lists.
- #488 owns ImportRegistry path privacy.
- #455/#472 and #458/#460/#463/#470 own bounded D04 security/convergence scopes; integrate only after exact-head evidence and dependency review.
- #468 owns Training progress crash recovery but remains blocked on opened-object identity/security review until that is resolved.
- #478 owns current-base Library source/provenance catalog convergence.

## Current release gates
1. #467 must terminalize GREEN on exact head or produce a real new blocker; #435 broad RED cannot be bypassed by weakening owner locks.
2. #441 must terminalize across its still-queued Formats/Data Upgrade gates in addition to already-GREEN Windows Composition/UI Semantic/D01 PGN.
3. #448 must terminalize. Only then create one fresh runtime-data recomposition from exact accepted bytes; never revive stale #464/#466 as candidate authority.
4. #454 must terminalize or be explicitly superseded by accepted #467 evidence.
5. #469/#475 and #495 must terminalize in dependency order before PGN/Book review projection enters the refreshed release candidate.
6. #491 must terminalize before release can claim one persisted language across Stage1/V2 surfaces.
7. #498 must close the composition-root startup leak without creating a second runtime owner.
8. #510/#515 must terminalize before Books ingestion can claim canonical list semantics across Markdown/HTML.
9. #488 and relevant D04 security/privacy children must terminalize before release intake.
10. #462 must terminalize before fresh Windows accessibility/package QA.
11. W1 #444/#447, W2 #468/#478 and current #448 must be reconciled in dependency order; blocked adapters must remain explicit rather than holding unrelated release work hostage.
12. Produce exactly one fresh Windows candidate/package only from the refreshed non-stale stack and obtain exact-machine packaged runtime evidence. Never reuse a rejected ZIP.
13. Human NVDA acceptance remains open. `NVDA_VERIFIED=NO` until Oleksii personally tests the exact fresh candidate.
14. ChessBase-family capability truth remains explicit SUPPORTED/PARTIAL/UNSUPPORTED/BLOCKED; unsupported formats must not be marketed as supported or block unrelated desktop release completion.

## Worker routing
### W1 — Formats / GameTree / interoperability
KEEP. Finish #444/#447 and D04 isolated/security evidence without collapsing distinct ownership. Prefer terminal exact evidence and current-base convergence, not new duplicate parsers.

### W2 — Library / database / books / training content
PROMOTE #448 as the data-release dependency; keep #468 blocked until its identity/security issue is resolved and continue #478 only through its current owner. For Books ingestion, #510 owns Markdown and #515 owns HTML. Avoid #441 runtime composition and W4 accessibility surfaces.

### W3 — User workflows / desktop composition
KEEP evidence/review role around current #441. #473 is consumed by #491; #471 by #475; #479 by #495; #481 by explicit startup-cleanup successors. Do not create new Product implementations for those already-owned defects.

### W4 — Windows / NVDA / accessibility / package QA
PROMOTE #462 as current accessibility successor. After the refreshed runtime/data/security stack is stable, build one fresh candidate and exact-machine QA. Never reuse rejected packages and never claim human NVDA verification.

### W5 — Integration / release / coordination
PROMOTE. Immediate job is dependency hygiene and convergence: keep #467/#454/#441/#448/#469/#475/#495/#491/#498/#488/#510/#515/#462 under exact-head watch; keep stale/duplicate stacks out of release authority; intake only terminal verified packages in dependency order. Do not create a second umbrella.

## Codex Cloud / Work
Codex Cloud: safe work is a bounded exact-head release/integration repair that does not touch currently reserved Product surfaces. Prefer CI/evidence topology, collision cleanup, or a demonstrably disjoint current-base blocker.

Work: first resolve ownership races/duplicates and stale release authority. Then take independent exact-head release/user-journey evidence only where no current Product/evidence owner exists. Do not manufacture work by duplicating an active lane.

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
- Real V2 Windows composition exists and exact #441 Windows Composition/UI Semantic/D01 PGN gates are GREEN, but the full exact-head release chain is not terminal because other gates remain queued and several stacked Product/security/data repairs are still pending.
- Old runtime/package authority is stale; #464/#466/#480 cannot be promoted.
- No fresh final Windows ZIP is accepted in this epoch.
- Automated accessibility/semantic CI does not equal human NVDA acceptance.
- `NVDA_VERIFIED=NO`.

## Next audit trigger
Audit immediately when any of these occurs: #467 terminal GREEN/RED; #441 queued gates terminalize; #448 terminalizes; #454 terminalizes/supersedes; #469/#475/#495 terminalize; #491 or #498 terminalizes; #488/#510/#515 terminalize; #462 terminalizes; a fresh runtime-data recomposition appears; a fresh Windows candidate appears; a major security child becomes intakeable; ownership collides/stales again. Otherwise continue the highest-priority disjoint work after a fresh live collision scan.
