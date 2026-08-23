# DEV3 NEXT WORK

Canonical priority remains STAGE1 RELEASE FREEZE / ONE FRESH WINDOWS CANDIDATE WIP.

Accepted Stage1 authority is `manual5/integration-20260821 @ 1e9d23b034e6d347fe03c3581469a07e16037c55`.

Promoted Stockfish runtime privacy is independently GREEN in DEV3 PR #192 at QA head `6160132618363f75b071510fd09c9c98af6517fa`: run `32638464690`, Windows job `97191677872` SUCCESS, Ubuntu job `97191677953` SUCCESS. Required evidence: 21/21 Stockfish+UCI recovery, 6/6 privacy including immutable PR #159 oracle, 65/65 focused release/accessibility, exact authority/scope/diff/compile/oracle-blob gates PASS.

Highest DEV3 priority on every continuation:
1. fresh-read DEV5 candidate PR #175 and current accepted integration SHA before any action;
2. search for an active DEV1/UI repair for the proven V5 board-focus continuity defect; do not create a competing UI Product implementation;
3. preserve V5 strict evidence already GREEN: original Move Edit classification A, Backspace e9->e, Ctrl+A selection/delete, Ctrl+A/Ctrl+C clipboard e9, 64 squares and board-origin a3 focus;
4. preserve the exact blocker assertion: UIA Invoke of `move-submit` must restore/retain semantic board-origin focus after the move. Do not weaken it or substitute timing-only acceptance;
5. owner repair must address actual event routing: the current HTML listener captures original `submitMove`, while bootstrap later only reassigns `window.submitMove`; ensure the real click/UIA Invoke path executes the current focus-policy submission function without creating a second core or changing canonical move semantics;
6. require regression coverage that exercises listener identity/routing, not merely source-string presence; preserve Enter behavior, original Move Edit identity, semantic focus cancellation rules and all native clipboard assertions;
7. after a DEV1-owned minimal Product repair is independently reviewed, DEV5/Audit must promote the exact reviewed SHA into the accepted Stage1 authority before the next fresh candidate. DEV3 must not move shared refs;
8. the next single candidate chain must start from exact promoted authority and rerun source identity/full regressions/privacy -> strict packaged UIA -> packaged Stockfish/sound -> release preflight -> ZIP reopen/hash/identity -> artifact upload;
9. no artifact from V5 run `32636245736` is a candidate ZIP; the chain stopped at board-focus continuity before downstream package certification;
10. only a newly proven DEV3-owned Stockfish/runtime/analysis/clock/lifecycle defect justifies DEV3 Product mutation during freeze;
11. NVDA remains unverified until the user personally verifies the exact fresh candidate.

Terminal DEV3 Full Product PR #137 remains technically GREEN for later selective intake and is separate from Stage1 release authority. PR #176 is supporting real-Stockfish evidence only. PR #159 is historical defect proof.

SAFE_OVERLAP=YES
PROMOTED_STAGE1_SHA=1e9d23b034e6d347fe03c3581469a07e16037c55
PROMOTED_PRIVACY_CI=GREEN
DEV3_PRODUCT_PATCH_REQUIRED=NO
V5_BOARD_FOCUS_PRODUCT_DEFECT=PROVEN_DEV1_OWNED
FRESH_WINDOWS_CANDIDATE=NO
NVDA_VERIFIED=NO
