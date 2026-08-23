# DEV3 CURRENT STATE

DEV3 remains in SAFE OVERLAP release-support mode. No competing Product repair is open in the DEV3 lane.

CURRENT ACCEPTED STAGE1 AUTHORITY:
`manual5/integration-20260821 @ 1e9d23b034e6d347fe03c3581469a07e16037c55`. This is the promoted Stockfish runtime diagnostic privacy repair; the Product delta from old `80720e8125c59a213f278668d599040f2768d553` is confined to `acs/stockfish_runtime.py`.

PROMOTED PRIVACY REPLAY IS NOW GREEN:
DEV3 QA-only PR #192 exact head `6160132618363f75b071510fd09c9c98af6517fa`, exact base `1e9d23b...`.
Workflow `DEV3 Promoted Stockfish Privacy Evidence`, run `32638464690`:
- Windows Server 2025 job `97191677872`: SUCCESS;
- Ubuntu 24.04 job `97191677953`: SUCCESS.
Logged Ubuntu gates, with the same substantive steps GREEN on Windows: Stockfish runtime + DEV3 UCI recovery `21/21`; immutable PR #159 privacy oracle 3 plus promoted replay 3 = `6/6`; focused release/accessibility `65/65`; exact base/scope, diff hygiene, compile and immutable oracle blob identity PASS. The earlier run `32638349278` was only a bad QA module invocation and did not prove a Product failure.

DEV3 real-engine PR #176 remains supporting Windows evidence against the repaired composition: official Stockfish 18, shared provider identity, MultiPV=5 restoration, legal move and packaged relative path all GREEN. It is not a release artifact.

CURRENT FRESH-CANDIDATE TRUTH:
DEV5 WIP=1 PR #175 targets exact accepted `1e9d23b...`. Run `32636245736`, job `97186343167`, reached a much later strict packaged gate than previous candidates. It proved original Move Edit topology classification A, native Backspace, Ctrl+A selection/delete and Ctrl+A/Ctrl+C clipboard behavior GREEN, plus 64 semantic board squares and board focus on `a3`.

The exact V5 blocker is board focus continuity after UIA Invoke of `move-submit`: expected focus to remain/restore to the board-origin square, but final focus is the original `move-input` Edit. Source inspection explains the runtime result: `web/index.html` registers `addEventListener('click', submitMove)` with the original function object; later `stage1_release_bootstrap.js` only assigns `window.submitMove = wrappedSubmit`. Reassignment does not replace an already registered listener callback, so UIA Invoke can execute original `submitMove()`, whose success path focuses move-input and bypasses `settleBoardFocusAfterInvoke`.

This is classified as a PROVEN STAGE1 UI/FOCUS PRODUCT DEFECT owned by DEV1, not a DEV3 Stockfish/runtime/analysis/clock/lifecycle defect and not a current native Ctrl+A/Ctrl+C defect. Existing source-shape focus tests can remain GREEN because they assert policy presence/order but do not execute the already-bound listener identity across wrapper reassignment. DEV3 recorded the classification on PR #175 in comment `5385923256` and did not mutate Product/UI or the candidate harness.

No fresh candidate ZIP was produced from V5 because downstream packaged Stockfish/sound lifecycle, preflight, ZIP identity and upload were skipped after the focus gate.

The terminal DEV3 Full Product slice remains PR #137 (`AnalysisService` provider-result resource bounds). Its previous exact coordination-head CI `32636305020 / 97186499314` is SUCCESS: focused `79/79`, full unittest `723/723`, pytest `801 + 651 subtests`, SELFTEST and complete diagnostic PASS.

SAFE_OVERLAP=YES
PROMOTED_STAGE1_SHA=1e9d23b034e6d347fe03c3581469a07e16037c55
PROMOTED_PRIVACY_CI=GREEN
DEV3_PRODUCT_PATCH_REQUIRED=NO
V5_NATIVE_SELECTION_COPY=GREEN
V5_BOARD_FOCUS_PRODUCT_DEFECT=PROVEN_DEV1_OWNED
FRESH_WINDOWS_CANDIDATE=NO
NVDA_VERIFIED=NO
