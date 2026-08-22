# AUTO-CHESS DEV3 current state

STATUS: COMPLETE / TERMINAL FOR CURRENT DEV3 SLICE / READY_FOR_INTEGRATION=YES
RUN_ID: 20260822-1845-batch-review
DIRECTIVE_SNAPSHOT: 18:00 wave; run began before the 19:00 directive boundary and therefore retained its snapshotted directive until terminal.

Lane: Full Product Engine/Analysis + ACSDB/Library/Search + presentation-neutral Books/Training/Teacher/Student backend contracts.

Current branch: `auto/dev3-batch-game-review-20260822`
Draft evidence PR: #96, base `auto/dev3-bookreader-snapshot-bounds-20260822`
Parent terminal BookReader head: `12763acb772e25524d58d58933a8f65b1f3434ea` / PR #95
Current executable Product/evidence head before terminal docs synchronization: `7db59c1a3538af2497972848ba706ba5bb07b3ea`
Exact executable CI: run `32583322210`, job `97055819000` — SUCCESS.

CURRENT PACKAGE — BOUNDED CANCELLABLE POST-GAME ENGINE REVIEW
- added presentation-neutral `GameReviewService` over the existing shared `AnalysisService`; no second engine provider or chess model;
- caller supplies explicit canonical FEN plus stable student/session/game/source-revision/position references;
- batch size <= 512; strict bounded IDs/FEN/depth and exact scalar contracts are checked before engine work;
- all positions in one batch must share one student/session/game/source revision and unique position IDs;
- cooperative cancellation is checked before and after every blocking engine call;
- cancellation arriving during a blocking call suppresses that just-finished answer, invalidates analysis generation and prevents later positions from starting;
- only one batch may run per service; a concurrent batch fails immediately with stable INVALID_SESSION/busy instead of queuing or invalidating the active batch;
- lock release is fail-safe, so a later batch can recover after cancellation/provider/cancel-provider failure;
- provider errors are sanitized to a stable application message and later positions continue;
- stale/unavailable points carry no score material;
- analyzed points carry transient depth/score metadata only and deliberately have no PV field;
- no engine PV/score is persisted in StudentProgress; existing data-minimization contract remains intact.

REAL COMPONENT EVIDENCE
Official Stockfish 18 `stockfish-ubuntu-x86-64-avx2.tar` was downloaded from the official release and hash-verified as `536c0c2c0cf06450df0bfb5e876ef0d3119950703a8f143627f990c7b5417964`.
The CI smoke ran the production `StockfishRuntime -> AnalysisService -> GameReviewService` path on two real positions and emitted `DEV3 OFFICIAL STOCKFISH 18 BOUNDED GAME REVIEW PASS`.
This is Linux backend engine evidence only, not Windows/NVDA evidence.

EXACT MACHINE EVIDENCE AT EXECUTABLE HEAD
- diff hygiene PASS
- compile PASS
- focused DEV3 data/engine-assisted/progress suite: 155/155 PASS
- full unittest: 685/685 PASS
- full pytest: 763 passed + 638 subtests
- SELFTEST PASS
- ACCESSIBLE CHESS 0.4 WEBVIEW2 COMPLETE USER FLOW DIAGNOSTIC PASS
- official Stockfish 18 bounded game-review smoke PASS
- no skip/xfail/test weakening used for GREEN.

PARENT PACKAGE SYNCHRONIZATION
PR #95 BookReader durable snapshot resource bounds is independently exact-GREEN at head `12763acb772e25524d58d58933a8f65b1f3434ea`, run `32580759442`, job `97049661061`: focused 143/143, unittest 673/673, pytest 751 + 628 subtests, diagnostic PASS. It is no longer CI-pending.

CROSS-LANE BLOCKER / DO NOT GUESS
Mistake/blunder classification is intentionally NOT implemented yet. The current DEV3 base does not expose an authoritative terminal StudentGame/Assignment actor/perspective contract. Raw UCI `score cp|mate` is not safe to subtract across alternating side-to-move plies without an explicit fixed perspective. DEV3 will not fabricate classification semantics or persist engine scores into StudentProgress. Resume this part only after the canonical student-game/actor/perspective linkage is terminal and ownership is clear.

OWNERSHIP
- DEV2 retains canonical GameTree/domain/core.
- DEV1 retains UI/WebView/Teacher/Classroom presentation and current downstream Classes/Students/Lessons/Assignments/Remote surface.
- DEV4 retains shared PGN/ChessBase/import Product-security/data-loss repair ownership.
- DEV5 retains selective integration/promotion.
- frozen Stage1 release lineage untouched.

P0 DEV3-owned: none known open in this slice.
P1 DEV3-owned: none known open in this slice.
READY_FOR_INTEGRATION=YES for this isolated backend package.
OVERALL_FULL_PRODUCT_DEV3=PARTIAL / next semantic classification step is cross-lane dependent.
FRESH_WINDOWS_CANDIDATE=NO.
NVDA_VERIFIED=NO.
