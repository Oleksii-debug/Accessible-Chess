# Accessible Chess — Autonomous Routing Control

EPOCH: CHESS-2026-09-08-17
STATE: ACTIVE — FIVE HOURLY WORKERS + WORK COMPLETION OWNER

## Operating invariant
Every worker, Codex Cloud and Work run must reconstruct newest repository/PR/CI/runtime truth before substantive work. Classify inherited targets KEEP, CHANGE, STOP_STALE, COLLISION or PROMOTE. Do not duplicate active ownership.

## Product priority
Converge Version 2 formats/library/books/workflows into one usable Windows/NVDA release candidate without violating Stage 1 release or accessibility boundaries.

Canonical dependency order: GameTree/PGN -> ACSDB/Library -> ChessBase adapters -> Books/Training -> later Teacher/Classroom/Web.

## Live convergence snapshot — 2026-09-08 07:52Z
- #435 remains the single Formats umbrella/convergence authority. #467 broad Formats convergence is terminal GREEN and has been physically intaken into #435; #568 clock-oracle repair is included. Do not create a second umbrella or revive #454.
- #441 remains the single V2 runtime/application authority. W5 created bounded compose PR #569 from refreshed #435 into #441 after a fresh collision scan; #569 was mergeable and was merged. Current #441 head is `8802785fbd38f10b8431b5069dcb2931472c7a81` and therefore now physically includes refreshed #435/#467 Formats history plus prior #551/#567 runtime fixes.
- The only file changed independently on both sides of the pre-compose ancestry was `acs/library_webview_projection.py`; inspection proved the two deltas were identical, so no Product semantic conflict existed.
- Fresh exact-head #441 workflows are running on the combined candidate: Windows Composition, UI Semantic, D01 PGN, data-upgrade V6, tracked-writer, frozen Stage1 blob contract and D06 nested-comment checks.
- W1 D06 nested-comment preflight run `34201473198` is RED only at `Prove exact child scope and current parent ancestry` on both Ubuntu and Windows before Product tests. Treat this as topology/preflight evidence, not a Product regression, unless later executable Product evidence contradicts it.
- #536 remains sole P0 external-review/live-state isolation Product owner and is terminal GREEN / PROMOTE-ready, but do not intake until the new combined #441 broad/Windows gate terminalizes.
- #543 remains terminal-green Book->Board baseline. #560 remains terminal-green Library->PGN visible-route refresh and PROMOTE-ready after the same combined gate.
- #448 remains shipped-V1 executable-local data bridge and must terminalize before fresh runtime-data recomposition.
- #518 Book progress/open atomicity, #555 D07 filtered export streaming, #478 Library source/provenance catalog, #491/#532 language, #488 privacy, #562 D06 resume-lock TOCTOU, #541 EPUB ingress and #565/#558/#530 package path retain their current owners. Do not duplicate.

## Completed / DO NOT REPEAT
- #436 bounded PGN ingress for BookTraining.
- #437 dirty-PGN open/discard guard.
- #438 V2 UI semantic/accessibility CI expansion.
- #439 Windows file-workflow UI-thread fail-closed repair.
- #443 owner-bound dirty-PGN discard confirmation.
- #444/#447 nested-comment PGN convergence Product work.
- #457 package-preflight Windows superscript-device-alias repair.
- #461 D01 PGN convergence-aware CI topology repair.
- #543 Book->Board ordered repaint/focus baseline.
- #551 terminal Library-import UI wakeup self-recovery, merged into #441.
- #567 frozen Stage1 checkout normalization, merged into #441.
- #568 deterministic takeback-clock test oracle, merged into #467 then #435 and now composed into #441.
- #467 broad Formats owner-lock/evidence convergence, terminal GREEN and merged into #435.
- #569 controlled #435 -> #441 convergence compose, merged. Do not create a second compose/umbrella for the same ancestry.

## STOP_STALE / collision decisions
- #434 predecessor umbrella; #435 is successor.
- #440/#442/#445/#446 old W4 snapshots.
- #450 older V1 executable-data bridge; #448 is current.
- #453/#454 stale D07 lock repair attempts; #467 is canonical completed convergence.
- #465/#477 duplicate D01 topology repairs; #461 is canonical.
- #464/#466/#480 stale runtime/package ancestry; never package from them.
- #482/#483/#485/#486/#487/#489 stale/duplicate language implementations; #491 is canonical.
- #496/#499 duplicate Book-board implementations.
- #512 duplicate HTML-list implementation; #515 is canonical.
- #535/#542/#554 closed external-review predecessors; #536 is current Product owner.
- #546/#566 stale/evidence-only external-review branches; #559/#561 evidence only.
- #552/#557 closed Library->PGN predecessors; #560 is current terminal GREEN.
- #538 is RED-parent/evidence; #565 is current required-resource Product repair.
- #556 duplicate/evidence only; #551 is merged.
- #563/#564 duplicates of #518.

## Active reservations / collision boundaries
- #435 owns Formats umbrella/convergence authority.
- #441 owns Version2Application, runtime/release bootstrap, Windows composition and shared application boundary; it now includes refreshed #435/#467 via completed #569.
- #448 owns shipped-V1 executable-local data bridge.
- #536 owns P0 external-review Product delta awaiting selective intake.
- #543/#560 own accepted Book->Board baseline and Library->PGN route refresh.
- #491/#532 own persisted language and native-dialog localization in dependency order.
- #498 owns composition-root startup cleanup.
- #510/#515/#541 own Markdown/HTML/EPUB semantic ingestion scopes.
- #518 owns Book progress/open command atomicity.
- #488 owns ImportRegistry path privacy.
- #511/#565/#558/#530 own package/preflight layers.
- #562 owns only D06 resume-lock validation/open identity TOCTOU.
- #555 owns only D07 lazy complete filtered export; D06 remains sole PGN writer.
- #478 owns current-base Library source/provenance convergence.

## Current release gates
1. **Combined runtime + Formats gate:** #441@`8802785f...` must terminalize fresh Windows Composition plus broad Formats/D01/UI/data checks after #569 compose. Product-test GREEN is required before further intake.
2. **Topology-only W1 RED:** run `34201473198` failed before Product tests at ancestry proof; do not misclassify as Product RED or create a duplicate D06 repair from that alone.
3. **P0 external review:** PROMOTE #536 only after combined #441 gate is terminal and ancestry/collision review is clean.
4. **Accessibility route refresh:** PROMOTE #560 on accepted #543 baseline after the same combined gate.
5. #448 must terminalize before one fresh runtime-data recomposition.
6. #491 then #532 must terminalize before persisted/localized Windows language is claimed.
7. #498 must close startup cleanup without creating a second runtime owner.
8. #510/#515/#541, #518, #478/#555 and #488/#562 must terminalize/selectively converge before final release intake according to their exact scopes.
9. Package path remains #511 -> #565 plus #558 -> #530 with exact packaged-runtime evidence. No rejected ZIP may be reused.
10. Produce exactly one fresh Windows candidate/package from the refreshed non-stale stack.
11. Human acceptance remains `NVDA_VERIFIED=NO` until Oleksii personally tests that exact candidate.
12. ChessBase capability truth remains SUPPORTED/PARTIAL/UNSUPPORTED/BLOCKED; unsupported adapters must not block unrelated desktop release work.

## Worker routing
### W1 — Formats / GameTree / interoperability
KEEP disjoint owners only. #467 is completed/intaken; do not reimplement it. Continue #547 and #562 only through their existing scopes/evidence. Treat nested-comment ancestry/preflight failures as topology-only unless Product tests execute and fail.

### W2 — Library / database / books / training content
PROMOTE dependency-safe owners: #448, #518, #510/#515/#541, #555 and #478. Keep identity/security-blocked work blocked until its prerequisite is resolved. Do not duplicate runtime/application ownership.

### W3 — User workflows / desktop composition
PROMOTE. #536 remains next P0 Product intake after combined #441 terminalizes. Avoid collisions with #491/#532, #518 and W4 #543/#560.

### W4 — Windows / NVDA / accessibility / package QA
PROMOTE. Recheck exact combined #441. #543/#560 remain accepted accessibility packages. Build one fresh candidate only after runtime/data/security/package convergence. Never reuse rejected ZIPs or claim human NVDA verification.

### W5 — Integration / release / coordination
PROMOTE. #569 successfully composed refreshed #435/#467 into #441. Immediate gate is exact-head #441@`8802785f...` terminal CI. If Product-green, perform ancestry/collision review and selectively intake #536, then #560, rerunning relevant broad/Windows gates after each bounded intake. No second umbrella.

## Codex Cloud / Work
Codex Cloud: safest useful package is independent ancestry/collision review of #536 and #560 against combined #441@`8802785f...`; do not implement duplicate Product owners.

Work: verify end-to-end user journeys across combined #441 + terminal #536 + #543/#560 without editing reserved Product surfaces; distinguish topology/preflight failures from executable Product failures.

## Hard boundaries
- One canonical chess core; no chess rules in adapters/UI/Web.
- No duplicate umbrella/convergence implementation.
- No package from stale #464/#466/#480 lineage.
- No reuse of rejected Windows ZIPs.
- `NVDA_VERIFIED=NO` until Oleksii personally tests the exact fresh candidate.
- No paid services/compute without explicit approval.
- No silent invention/drop of source data.
- No raw local paths, tracebacks, provider internals or arbitrary adapter exception text in user-facing output.

## Windows/package/NVDA readiness truth
- Real V2 Windows composition exists and now physically includes refreshed broad Formats convergence in #441.
- Fresh combined #441 automated evidence is still running; no final release candidate is accepted yet.
- #536 external-review/live-state isolation is terminal GREEN and queued for selective intake after combined gate.
- #543 Book->Board and #560 Library->PGN are terminal GREEN and queued after the same gate.
- Data, Book transaction, language, security/privacy and package successors are not fully converged.
- Required-resource preflight remains #565; #558/#530 remain payload/assembler layers.
- No fresh final Windows ZIP is accepted in this epoch.
- Automated UIA/accessibility evidence does not equal human NVDA acceptance.
- `NVDA_VERIFIED=NO`.

## Next audit trigger
Audit immediately when #441@`8802785f...` terminalizes GREEN/RED on Product tests; #448 terminalizes; #491/#532, #518, #565/#558/#530, #562/#555/#478 become intakeable; selective intake of #536 or #560 occurs; a fresh runtime-data recomposition or Windows candidate appears; or ownership collides/stales again. Otherwise continue highest-priority disjoint integration work after a fresh collision scan.
