# DEV3 RUN STATE

RUN_ID: 20260823-promoted-privacy-green-v5-focus-classification
STATUS: SAFE_OVERLAP / RELEASE_SUPPORT / PROMOTED_PRIVACY_GREEN / V5_UI_FOCUS_BLOCKED
READY_FOR_INTEGRATION: NO_NEW_PRODUCT_CHANGE
OVERALL_FULL_PRODUCT_DEV3: PARTIAL

COORDINATION_BRANCH: auto/dev3-analysis-provider-bounds-20260823
TERMINAL_FULL_PRODUCT_SLICE: PR #137 / code commit 2e6e9e7767960c602d06a139948def6f9c400765 / validated head 7bcab25b54649663ba9f3094adbd14d49fdc3ced
PREVIOUS_EXACT_COORDINATION_CI: DEV3 Analysis Provider Bounds CI 32636305020 / 97186499314 SUCCESS; focused 79/79, full unittest 723/723, pytest 801 + 651 subtests, SELFTEST and complete diagnostic PASS.

PROMOTED_STAGE1_AUTHORITY:
- manual5/integration-20260821 @ 1e9d23b034e6d347fe03c3581469a07e16037c55
- old privacy-defective authority: 80720e8125c59a213f278668d599040f2768d553
- promoted Product delta: exactly acs/stockfish_runtime.py

DEV3 PROMOTED PRIVACY QA:
- PR #192 / branch qa/dev3-promoted-stockfish-privacy-evidence-20260823
- exact QA head: 6160132618363f75b071510fd09c9c98af6517fa
- exact base: 1e9d23b034e6d347fe03c3581469a07e16037c55
- initial run 32638349278 was QA invocation RED only: existing Stockfish runtime 18/18 passed, then a nonexistent test module name caused ModuleNotFoundError before the privacy oracle ran.
- invocation fixed without Product changes or assertion weakening.
- exact run 32638464690: Windows job 97191677872 SUCCESS; Ubuntu job 97191677953 SUCCESS.
- logged gates: Stockfish runtime + UCI recovery 21/21 PASS; immutable PR #159 oracle 3 plus promoted replay 3 = 6/6 PASS; focused release/accessibility 65/65 PASS; exact promoted SHA, two-file QA-only scope, diff hygiene, compile and immutable oracle blob identity PASS.
- classification: promoted Stockfish runtime privacy repair is independently GREEN.

DEV5 FRESH WINDOWS CANDIDATE V5:
- PR #175 / exact accepted source 1e9d23b034e6d347fe03c3581469a07e16037c55
- run 32636245736 / job 97186343167 is RED after substantial packaged evidence.
- before failure: full source regressions/diagnostic GREEN; immutable PR #159 privacy oracle 3/3 GREEN; original Move Edit topology classification A; native Backspace e9->e GREEN; native Ctrl+A selection/delete GREEN; native Ctrl+A/Ctrl+C clipboard e9 GREEN; board exposes 64 squares and a3 receives semantic focus.
- exact failure: after UIA Invoke of move-submit, board focus does not restore/converge to a3; final focus is original move-input Edit runtime id 42.131498.4.5.1.3, name Хід.
- source correlation on accepted Product: index.html registers click listener with the original submitMove function object; later bootstrap only reassigns window.submitMove to a focus-policy wrapper. Existing registered listener therefore may keep calling the old callback, whose success path focuses move-input, exactly matching packaged runtime evidence.
- classification: PROVEN STAGE1 UI/FOCUS PRODUCT DEFECT, DEV1-owned. Not DEV3 Stockfish/runtime/analysis/clock/lifecycle, not current Ctrl+A/Ctrl+C defect, and not QA timing. DEV3 comment on PR #175: 5385923256.
- no candidate ZIP was assembled/uploaded from V5; downstream packaged Stockfish/sound lifecycle, preflight and ZIP identity were skipped after the focus gate.

OVERLAP DISCIPLINE:
- DEV3 does not patch DEV1 UI focus code or DEV5 candidate harness.
- no open DEV1 repair PR matching board focus continuity / move-submit focus / submitMove existed at the classification checkpoint.
- PR #176 remains supporting real Stockfish 18 repaired-runtime evidence; PR #159 remains historical defect proof.

CLASSIFICATION:
SAFE_OVERLAP: YES
PROMOTION_MATERIALIZED: YES
PROMOTED_STAGE1_SHA: 1e9d23b034e6d347fe03c3581469a07e16037c55
PROMOTED_PRIVACY_CI: GREEN
DEV3_PRODUCT_PATCH_REQUIRED: NO
V5_NATIVE_SELECTION_COPY: GREEN
V5_BOARD_FOCUS_PRODUCT_DEFECT: PROVEN_DEV1_OWNED
FRESH_WINDOWS_CANDIDATE: NO
NVDA_VERIFIED: NO

NEXT: fresh-read PR #175 and search for a DEV1-owned focus repair before any action. Do not duplicate UI repair. After a reviewed minimal Product repair makes actual move-submit/UIA Invoke route through the current focus-policy submission path and preserves Enter/canonical move/original Edit/native clipboard semantics, DEV5/Audit must promote the exact reviewed source before rerunning one fail-closed Windows candidate chain. DEV3 only reopens Product code for a newly proven DEV3-owned runtime/analysis/clock/lifecycle defect.
