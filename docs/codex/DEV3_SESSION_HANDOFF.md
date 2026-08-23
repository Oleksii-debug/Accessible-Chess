# DEV3 SESSION HANDOFF

DEV3 remained in SAFE OVERLAP release-support mode. No competing DEV3 Product repair was created.

PROMOTED AUTHORITY / PRIVACY VALIDATION:
Accepted Stage1 is now `manual5/integration-20260821 @ 1e9d23b034e6d347fe03c3581469a07e16037c55`.
DEV3 QA-only PR #192 current head `6160132618363f75b071510fd09c9c98af6517fa` replays privacy on that exact authority. The first run was QA invocation RED only; after fixing the nonexistent module reference without Product/assertion changes, exact run `32638464690` is GREEN on Windows `97191677872` and Ubuntu `97191677953`. Evidence: Stockfish runtime + UCI recovery `21/21`; immutable PR #159 privacy oracle plus promoted replay `6/6`; focused release/accessibility `65/65`; exact promoted SHA, two-file QA-only scope, diff hygiene, compile and immutable oracle blob identity PASS. Promoted privacy is therefore independently GREEN.

REAL ENGINE SUPPORT:
DEV3 PR #176 remains GREEN supporting evidence with official Stockfish 18, one shared runtime provider, MultiPV=5 restoration after engine play, legal move, packaged relative path, full regressions, SELFTEST and complete diagnostic. It is not a release archive or NVDA verification.

FRESH WINDOWS CANDIDATE V5:
DEV5 WIP=1 PR #175 targets exact accepted source `1e9d23b...`. Run `32636245736`, job `97186343167`, proves source/full regressions/privacy, original Move Edit topology classification A, native Backspace, Ctrl+A selection/delete, Ctrl+A/Ctrl+C clipboard, 64 semantic board squares and board-origin `a3` focus before failing at one later gate.

Exact blocker: after UIA Invoke of `move-submit`, board focus continuity does not converge; final focus is original `move-input` Edit runtime id `42.131498.4.5.1.3`, name `Хід`.

Source/runtime correlation is strong and deterministic:
- `web/index.html` registers `el('move-submit').addEventListener('click', submitMove)`, capturing the original callback object; base `submitMove()` focuses move-input on successful submission.
- `web/stage1_release_bootstrap.js::installMoveFocusPolicy()` later wraps the global function and assigns `window.submitMove = wrappedSubmit`, but this does not replace an already registered event-listener callback.
- UIA Invoke can therefore execute the old callback and bypass `settleBoardFocusAfterInvoke`, exactly matching the packaged final focus.
- existing source-shape tests verify intended focus-policy code exists but do not execute stale listener identity through bootstrap reassignment.

Classification recorded on DEV5 PR #175 comment `5385923256`: PROVEN STAGE1 UI/FOCUS PRODUCT DEFECT, DEV1-owned; not a DEV3 engine/runtime/analysis/clock/lifecycle defect, not a current Ctrl+A/Ctrl+C defect and not QA timing. No matching open DEV1 repair PR existed at that checkpoint. DEV3 did not patch UI or helper.

V5 did not produce a certified candidate ZIP: downstream packaged Stockfish/sound lifecycle, release preflight, ZIP reopen/hash/identity and candidate upload were skipped after the strict focus failure. A build-only diagnostic artifact does not count as a candidate.

COORDINATION EVIDENCE:
The previous DEV3 coordination head was independently GREEN in `DEV3 Analysis Provider Bounds CI` run `32636305020`, job `97186499314`: focused `79/79`, full unittest `723/723`, pytest `801 + 651 subtests`, SELFTEST and complete diagnostic PASS.

NEXT:
Fresh-read PR #175 plus any newly opened DEV1 focus repair. Do not duplicate UI ownership. The minimal owner repair must make actual button click/UIA Invoke execute the current focus-policy submission path while preserving canonical move semantics, Enter behavior, original Move Edit identity and strict native-key/clipboard assertions. Add behavioral regression for listener routing. After independent review, DEV5/Audit must promote the exact repair SHA and then rerun exactly one full fail-closed candidate chain. DEV3 Product code only reopens for a newly proven DEV3-owned runtime/analysis/clock/lifecycle defect.

SAFE_OVERLAP=YES
PROMOTION_MATERIALIZED=YES
PROMOTED_STAGE1_SHA=1e9d23b034e6d347fe03c3581469a07e16037c55
PROMOTED_PRIVACY_CI=GREEN
DEV3_PRODUCT_PATCH_REQUIRED=NO
V5_NATIVE_SELECTION_COPY=GREEN
V5_BOARD_FOCUS_PRODUCT_DEFECT=PROVEN_DEV1_OWNED
FRESH_WINDOWS_CANDIDATE=NO
NVDA_VERIFIED=NO
