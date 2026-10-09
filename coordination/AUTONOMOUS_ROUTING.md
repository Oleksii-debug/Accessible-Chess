# Accessible Chess — Autonomous Routing Control

EPOCH: CHESS-2026-09-08-18
STATE: ACTIVE — FIVE HOURLY WORKERS + WORK COMPLETION OWNER

## Operating invariant
Every worker, Codex Cloud and Work run must reconstruct newest repository/PR/CI/runtime truth before substantive work. Classify inherited targets KEEP, CHANGE, STOP_STALE, COLLISION or PROMOTE. Do not duplicate active ownership.

## Product priority
Converge Version 2 formats/library/books/workflows into one usable Windows/NVDA release candidate without violating Stage 1 release or accessibility boundaries.

Canonical dependency order: GameTree/PGN -> ACSDB/Library -> ChessBase adapters -> Books/Training -> later Teacher/Classroom/Web.

## Live convergence snapshot — 2026-09-08 08:47Z
- #435 remains the single Formats umbrella/convergence authority. #467 broad Formats convergence is terminal GREEN and has been physically intaken into #435; #568 clock-oracle repair is included. Do not create a second umbrella or revive #454.
- #441 remains the single V2 runtime/application authority and still contains the completed #569 compose of refreshed #435/#467 plus prior #551/#567 runtime fixes. The current exact #441 head advanced to `f33ee75ccadd181ab24a82133a34f9188b2e49f5` through owner-local native Windows/WebView2 verification cleanup and trigger wiring; do not use the older `8802785f...` checkpoint as current truth.
- Exact-head #441 Windows Composition, UI Semantic, D01 PGN, data-upgrade V6, tracked-writer and frozen Stage1 blob contract are terminal GREEN.
- The re-enabled broad Formats gate now executes on #441 pushes. Both combined-format matrices (`windows-2025` and `ubuntu-22.04`) are terminal GREEN with owner locks, semantic journeys, full unittest/pytest and diagnostics. The separate `real-pinned-chessbase` job is still running its real CBH/CBV -> canonical GameTree/schema-v6 Library journey, so the combined gate is not terminal yet.
- W1 D06 nested-comment preflight/framer checks remain RED before Product execution at ancestry/topology proof. Treat them as topology/preflight evidence, not a Product regression, unless later executable Product evidence contradicts it.
- #536 remains sole P0 external-review/live-state isolation Product owner and terminal GREEN / PROMOTE-ready. Fresh W5 collision review confirms its intended Product delta is still needed, but current #441 `version2_release_ui.py` has newer native UI-thread ownership/lifecycle structure absent from #536's old base. Therefore do not wholesale merge or blindly replace that file; selective conflict-resolved composition is required after the combined gate terminalizes. `version2_release_app.py` also needs only the bounded projector binding `api.project_review_fen` alongside that UI delta.
- #543 remains terminal-green Book->Board ordered repaint/focus baseline. #560 remains terminal-green Library->PGN visible-route refresh, but W4 proved current #441 still lacks #543's ordered Stage1 repaint/focus barrier. Intake order is therefore #543-equivalent accepted behavior first, then #560; do not cherry-pick only #560 tip.
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
- #543 Book->Board ordered repaint/focus baseline (terminal-green accepted baseline; its behavior still must be selectively composed into current #441 before #560).
- #551 terminal Library-import UI wakeup self-recovery, merged into #441.
- #567 frozen Stage1 checkout normalization, merged into #441.
- #568 deterministic takeback-clock test oracle, merged into #467 then #435 and composed into #441.
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
- #441 owns Version2Application, runtime/release bootstrap, Windows composition, native UI thread/lifecycle and shared application boundary; it includes refreshed #435/#467 via completed #569.
- #448 owns shipped-V1 executable-local data bridge.
- #536 owns P0 external-review Product delta awaiting selective conflict-resolved intake; do not duplicate or wholesale replace current #441 runtime files from its old base.
- #543/#560 own accepted Book->Board baseline and Library->PGN route refresh; preserve their dependency order.
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
1. **Combined runtime + Formats gate:** #441@`f33ee75c...` has terminal GREEN Windows Composition/UI/D01/data/frozen-blob evidence and terminal GREEN broad matrix jobs on Windows+Ubuntu. `real-pinned-chessbase` is still running; wait for its terminal result before Product intake.
2. **Topology-only W1 RED:** current nested-comment preflight/framer REDs occur before Product tests at ancestry proof; do not misclassify them as Product RED or create duplicate D06 repair from that alone.
3. **P0 external review:** after gate 1 terminalizes GREEN, selectively compose #536 into current #441 while preserving #441 native thread/lifecycle guards. No wholesale old-base file replacement.
4. **Accessibility route refresh:** after #536 re-gates, selectively compose accepted #543 ordered repaint/focus behavior into #441, then #560 Library->PGN refresh, rerunning Windows/broad/accessibility evidence after each bounded intake.
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
KEEP disjoint owners only. #467 is completed/intaken; do not reimplement it. Continue #547 and #562 only through their existing scopes/evidence. Treat nested-comment ancestry/preflight failures as topology-only unless Product tests execute and fail. Observe the current #441 pinned ChessBase job rather than starting a duplicate corpus run.

### W2 — Library / database / books / training content
PROMOTE dependency-safe owners: #448, #518, #510/#515/#541, #555 and #478. Keep identity/security-blocked work blocked until its prerequisite is resolved. Do not duplicate runtime/application ownership.

### W3 — User workflows / desktop composition
PROMOTE. #536 remains next P0 Product intake after combined #441 terminalizes. Preserve current #441 native UI-thread/lifecycle code during selective composition. Avoid collisions with #491/#532, #518 and W4 #543/#560.

### W4 — Windows / NVDA / accessibility / package QA
PROMOTE. Exact #441 automated Windows evidence is green except the combined Formats gate is still awaiting terminal pinned ChessBase. Preserve #543 -> #560 intake order. Build one fresh candidate only after runtime/data/security/package convergence. Never reuse rejected ZIPs or claim human NVDA verification.

### W5 — Integration / release / coordination
PROMOTE. Current authority is #441@`f33ee75c...`. Wait only for terminal `real-pinned-chessbase`; if GREEN, perform selective conflict-resolved #536 intake preserving current UI-thread/lifecycle guards and rerun broad + Windows gates. Then compose accepted #543 behavior followed by #560, with a gate after each bounded intake. No second umbrella.

## Codex Cloud / Work
Codex Cloud: safest useful package is independent patch-level review of the #536 selective compose against current #441 native UI-thread/lifecycle structure, plus #543 -> #560 ordering verification. Do not implement duplicate Product owners.

Work: verify end-to-end user journeys across current #441 + intended #536 + #543/#560 without editing reserved Product surfaces; distinguish topology/preflight failures from executable Product failures and pay particular attention to live-game preservation during PGN/Book review and visible focus after Book/Library route changes.

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
- Real V2 Windows composition exists and physically includes refreshed broad Formats convergence in #441.
- Current exact #441 Windows Composition, UI Semantic, D01, data-upgrade and frozen Stage1 evidence are GREEN; broad Windows+Ubuntu matrix jobs are GREEN; pinned real ChessBase evidence is still running, so no final release candidate is accepted yet.
- #536 external-review/live-state isolation is terminal GREEN and queued for selective conflict-resolved intake after the combined gate.
- #543 Book->Board and #560 Library->PGN are terminal GREEN but must be composed in that order onto current #441.
- Data, Book transaction, language, security/privacy and package successors are not fully converged.
- Required-resource preflight remains #565; #558/#530 remain payload/assembler layers.
- No fresh final Windows ZIP is accepted in this epoch.
- Automated UIA/accessibility evidence does not equal human NVDA acceptance.
- `NVDA_VERIFIED=NO`.

## Next audit trigger
Audit immediately when #441@`f33ee75c...` pinned ChessBase job terminalizes GREEN/RED; selective intake of #536/#543/#560 occurs; #448 terminalizes; #491/#532, #518, #565/#558/#530, #562/#555/#478 become intakeable; a fresh runtime-data recomposition or Windows candidate appears; or ownership collides/stales again. Otherwise continue highest-priority disjoint integration work after a fresh collision scan.
