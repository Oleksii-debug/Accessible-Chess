# DEV3 CURRENT STATE

DEV3 remains in SAFE OVERLAP release-support mode. No competing DEV3 Product repair is open.

CURRENT ACCEPTED STAGE1 AUTHORITY:
`manual5/integration-20260821 @ 1e9d23b034e6d347fe03c3581469a07e16037c55`.

PROMOTED PRIVACY / ENGINE SUPPORT:
DEV3 QA PR #192 exact head `6160132618363f75b071510fd09c9c98af6517fa` is GREEN on exact accepted authority: run `32638464690`, Windows `97191677872` SUCCESS, Ubuntu `97191677953` SUCCESS; 21/21 Stockfish+UCI recovery, 6/6 privacy including immutable PR #159, and 65/65 focused release/accessibility. DEV3 PR #176 remains GREEN supporting official Stockfish 18 real-runtime evidence. Neither is a candidate ZIP or human NVDA evidence.

CURRENT RELEASE COMBINATION:
DEV5 PR #195 `release/dev5-stage1-combined-repair-20260823` has live head `5e8ca72f7dd552ee151ebd5b85c52148004ac307`, based on accepted `1e9d23b...`. It is an intermediate RELEASE_HOLD surface carrying accepted Stockfish privacy + history fail-closed work. DEV2 PR #199 handles a separately proven oversized-FEN-counter exception-domain defect; final Stage1 authority cannot advance until that repair and the UI focus repair are reconciled and independently accepted.

V5 UI DEFECT:
DEV5 V5 run `32636245736 / 97186343167` already proved original Move Edit topology classification A, native Backspace, native Ctrl+A selection/delete, Ctrl+A/Ctrl+C clipboard, 64 board squares and board-origin `a3` focus. Its strict failure occurs only after UIA Invoke of `move-submit`: final focus is the original `move-input` Edit instead of restored board-origin focus.

Root cause remains deterministic: `web/index.html` registers the original `submitMove` function object as the button listener before `stage1_release_bootstrap.js::installMoveFocusPolicy()` replaces `window.submitMove`. Reassigning the global does not change the callback already installed by `addEventListener`, so UIA Invoke can bypass the wrapped focus-policy path. This is a DEV1/UI Product defect, not DEV3 engine/runtime/analysis/clock/lifecycle and not current Ctrl+A/Ctrl+C failure.

ACTIVE PRODUCT OWNER:
AUTOPULSE D01 PR #197 now owns the UI repair. Current exact head is `53fff92a18c22a1a555583203461f7b0214041ff`, base `574d8c7344a7490de46ba38498f363395c951019`. Its sidecar implementation adds `web/stage1_submit_focus_route.js` and a third packaged evaluate_js stage.

Exact D01 run `32638711537` is not release-green. Focus/release contracts are `61/61 PASS`, but full unittest is RED on Ubuntu job `97192322458` and Windows job `97192322603`. Ubuntu reports `674` tests with exactly `3` failures: two existing fail-closed resource tests now encounter the new submit-focus resource before the locked board-bridge failure, and saturation composition expects the existing two evaluate_js stages but observes three. Later pytest/SELFTEST/diagnostic are skipped.

Independent DEV5 QA PR #196 encodes the stronger minimal topology contract: remove the original button callback and rebind the same element to `wrappedSubmit` inside `installMoveFocusPolicy()`. Current PR #197 sidecar does not meet that oracle. DEV3 comment `5385949040` asks the owner not to weaken existing contracts and recommends direct listener rebind inside the existing bootstrap, preserving packaged resource order/surface, Enter behavior, original Move Edit identity, canonical move submission and native clipboard assertions.

DEV3 coordination head immediately before this update, `d9afdf70e7812392fe8cbd98ea2d2a20e5d4abb6`, has exact GREEN CI `32638710253 / 97192329830`: focused `79/79`, full unittest `723/723`, pytest `801 + 651 subtests`, SELFTEST and complete diagnostic PASS.

SAFE_OVERLAP=YES
DEV3_PRODUCT_PATCH_REQUIRED=NO
PROMOTED_STAGE1_SHA=1e9d23b034e6d347fe03c3581469a07e16037c55
PROMOTED_PRIVACY_CI=GREEN
SUBMIT_FOCUS_OWNER=PR197
PR197_CURRENT_FULL_CI=RED
FRESH_WINDOWS_CANDIDATE=NO
NVDA_VERIFIED=NO
