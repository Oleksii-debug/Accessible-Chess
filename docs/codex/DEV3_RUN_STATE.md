# DEV3 RUN STATE

RUN_ID: 20260823-1216-submit-focus-owner-safe-overlap
STATUS: SAFE_OVERLAP / RELEASE_SUPPORT / UI_REPAIR_OWNED / NO_DEV3_PRODUCT_MUTATION
READY_FOR_INTEGRATION: NO_NEW_DEV3_PRODUCT_CHANGE
OVERALL_FULL_PRODUCT_DEV3: PARTIAL

COORDINATION_BRANCH: auto/dev3-analysis-provider-bounds-20260823
TERMINAL_FULL_PRODUCT_SLICE: PR #137 / code commit 2e6e9e7767960c602d06a139948def6f9c400765 / validated head 7bcab25b54649663ba9f3094adbd14d49fdc3ced
LAST_EXACT_COORDINATION_HEAD: d9afdf70e7812392fe8cbd98ea2d2a20e5d4abb6
LAST_EXACT_COORDINATION_CI: DEV3 Analysis Provider Bounds CI 32638710253 / 97192329830 SUCCESS; focused 79/79, full unittest 723/723, pytest 801 + 651 subtests, SELFTEST and complete diagnostic PASS.

ACCEPTED STAGE1 AUTHORITY:
- manual5/integration-20260821 @ 1e9d23b034e6d347fe03c3581469a07e16037c55
- DEV3 promoted privacy replay PR #192 exact run 32638464690 is GREEN on Windows 97191677872 and Ubuntu 97191677953.
- DEV3 real Stockfish 18 supporting PR #176 remains GREEN; neither PR is a release archive or NVDA verification.

CURRENT CONTROLLED RELEASE SURFACE:
- DEV5 PR #195 uses release/dev5-stage1-combined-repair-20260823; current live head 5e8ca72f7dd552ee151ebd5b85c52148004ac307, base remains accepted 1e9d23b...
- this combined surface already carries accepted Stockfish privacy + history fail-closed work but is explicitly RELEASE_HOLD / not final authority.
- DEV2 PR #199 is an additional P1 oversized-FEN-counter fail-closed repair. Its current CI is not terminal Product approval; release remains held until DEV2/Audit/DEV5 finish selective intake and exact combined validation.

V5 PACKAGED ROOT CAUSE:
- V5 PR #175 / run 32636245736 / job 97186343167 proved original Move Edit classification A, native Backspace, Ctrl+A selection/delete, Ctrl+A/Ctrl+C clipboard, 64 squares and board-origin a3 focus before failing after UIA Invoke of move-submit.
- accepted source binds addEventListener('click', submitMove) before bootstrap replaces window.submitMove, so the installed listener retains the stale function object and bypasses the focus wrapper.
- classification remains PROVEN STAGE1 UI/FOCUS PRODUCT DEFECT, not DEV3 engine/runtime/analysis/clock/lifecycle.

ACTIVE UI OWNER:
- AUTOPULSE D01 PR #197 is now the active Product repair owner; current exact head 53fff92a18c22a1a555583203461f7b0214041ff, based on combined parent 574d8c7344a7490de46ba38498f363395c951019.
- current implementation adds a third packaged JS resource `web/stage1_submit_focus_route.js` plus loader changes.
- D01 run 32638711537: focused focus/release contracts 61/61 PASS, but full unittest fails on both Ubuntu job 97192322458 and Windows job 97192322603.
- Ubuntu full discovery: 674 tests, exactly 3 failures. Existing resource-error and saturation contracts observe the new submit-focus resource before the locked board-bridge error and observe 3 evaluate_js calls instead of the existing 2. Pytest/SELFTEST/diagnostic are skipped after full unittest RED.
- independent DEV5 QA PR #196 requires the actual preinstalled listener to be removed and rebound to wrappedSubmit inside installMoveFocusPolicy. Current sidecar does not satisfy that stronger topology oracle.
- DEV3 posted review comment 5385949040: do not weaken existing contracts; prefer direct removeEventListener/addEventListener rebind inside the existing bootstrap so packaged resource surface/order remains unchanged.

OVERLAP DISCIPLINE:
- do not push to PR #197, PR #196, PR #199, PR #195 or DEV5 candidate branches.
- do not create a second UI repair.
- next DEV3 action is independent validation only after the active owner publishes a new exact repair head.
- only a newly proven DEV3-owned Stockfish/runtime/analysis/clock/lifecycle defect justifies DEV3 Product mutation during Stage1 freeze.

SAFE_OVERLAP: YES
DEV3_PRODUCT_PATCH_REQUIRED: NO
PROMOTED_PRIVACY_CI: GREEN
SUBMIT_FOCUS_OWNER: PR197
PR197_CURRENT_HEAD: 53fff92a18c22a1a555583203461f7b0214041ff
PR197_CURRENT_FULL_CI: RED
FRESH_WINDOWS_CANDIDATE: NO
NVDA_VERIFIED: NO
