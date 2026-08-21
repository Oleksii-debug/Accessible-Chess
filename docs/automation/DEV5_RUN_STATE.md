# DEV5_RUN_STATE

RUN_ID: 20260822-0008
STARTED_LOCAL: 00:08:42 Europe/Kyiv
STATUS: COMPLETE
MODE: COORDINATOR_ACTIVE
COORDINATION_BRANCH: manual5/dev5-regression-integration-20260821
DEV4_VALIDATION_BRANCH: manual5/dev5-reconcile-dev4-20260822
DEV2_VALIDATION_BRANCH: manual5/dev5-reconcile-dev2-20260822
INTEGRATION_TARGET: manual5/integration-20260821
INTEGRATION_START_SHA: e24ff85ff9a6ad3ea19d33f7035526c7bcdf2c8e
INTEGRATION_FINAL_SHA: 0fa442330bc2bb03636ff9297512da4c29e38684
SNAPSHOT_CUTOFF: 2026-08-22T00:08:42+03:00
SNAPSHOT_POLICY: coordinated DEV1-DEV4 only from terminal evidence that existed before the cutoff; later DEV3/DEV4 handoff mutations were observed but excluded from intake decisions
NVDA_VERIFIED: NO
FRESH_WINDOWS_CANDIDATE: NO
STAGE_2: BLOCKED

## Stage1 closure completed
- DEV1 accepted semantics remain authoritative and integrated; no duplicate intake.
- DEV3 accepted backend package remains integrated; no duplicate intake.
- DEV4 terminal source considered for this wave: a4209d005ea0a1476f8eafb4822f4d39ac50ee5a. Whole-branch merge was rejected; DEV5 selectively reconciled the safe Product package on top of known-green e24ff85f.
- DEV4 reconciliation final head: abff45ebcc4b5af2a85ab0c456b025b5098c6e29 on manual5/dev5-reconcile-dev4-20260822. PR #66 remains draft / DO NOT MERGE.
- DEV4 exact-head UI Semantic Gate 32532343385 SUCCESS.
- DEV4 exact-head Stage1 Saturation Hardening CI 32532343373 SUCCESS, including compile, JS reinjection, architecture/frozen-scope, move/board/history/editor, engine/clocks/lifecycle/analysis, sound/settings/native-menu/keymap/release composition, Stockfish 18, full unittest, full pytest and diagnostic.
- DEV4 reconciliation intentionally excludes lane-only .github/workflows/dev4-package-security-ci.yml and all QA-owned strict Windows workflow changes.
- DEV4 reconciliation includes settings fail-closed hardening, release_preflight, packaged WebView runtime completeness checks, WebView2 debugger/security sanitization, path-private resource errors, keymap boundary hardening, obsolete release-workflow tombstones, and transactional board-bridge reconciliation preserving accepted DEV1 ordering/readiness/routing semantics.
- A first attempted board reconciliation head 998b71da629a504806010793f9c5d24014ae24fb was correctly rejected by saturation CI because one accepted DEV1 ordering regression failed. Tests were not weakened. DEV5 fixed Product ordering at abff45e while retaining render-failure anti-stacking behavior; both canonical gates then went GREEN.
- manual5/integration-20260821 was fast-forwarded, not merged through PR #66, to abff45e after exact GREEN evidence.

## Terminal DEV2 intake completed
- Terminal pre-cutoff DEV2 head: 8b74ef94c91dbed8d9dfc73bcb39a9aa956a9afe.
- Source delta from accepted DEV2 baseline 01623b9b7d19c106e61fa0ccc66cda2b8f2aa391 is exactly two files: acs/chesscore.py and tests/test_dev2_fen_atomicity.py.
- Before intake, the integration chesscore blob exactly matched DEV2 accepted-baseline blob 743d5ab98bdf1855f9efaacb40a6b0003c63dce6, proving no unrelated post-DEV2 chesscore changes would be overwritten by final-state port.
- DEV2 validation head: 0fa442330bc2bb03636ff9297512da4c29e38684 on manual5/dev5-reconcile-dev2-20260822. Draft PR #70 remains DO NOT MERGE.
- DEV2 exact-head UI Semantic Gate 32532503184 SUCCESS.
- DEV2 exact-head Stage1 Saturation Hardening CI 32532503262 SUCCESS, including full unittest, full pytest, Stockfish 18 and complete diagnostic.
- manual5/integration-20260821 was fast-forwarded to exact validated head 0fa442330bc2bb03636ff9297512da4c29e38684.

## Full-product plane assessment
- Requested docs/codex/CURRENT_STATE.md, NEXT_WORK.md and SESSION_HANDOFF.md were not present on the inspected live full-product refs; no nonexistent file was treated as evidence.
- PR #52 shared-core head is 6fa705f7ca80ee69b4183f99c9bc1c5a86048e64 and its own live description still records the independent audit input as RETURN TO WORK before later fixes.
- codex/full-product-20260821 is not a substantive reusable full-product baseline; completion/full-product-critical-path-20260819 contains broader future work but is not safe for wholesale adoption without exact package-by-package audit/intake.
- Therefore no full5/integration-20260821 ref was created. Creating one from an unaudited aggregate would violate the no-blind-merge rule. Future full-product work remains package-by-package only.

## Release boundary
- PR #54 and frozen release refs untouched.
- No old rejected ZIP reused.
- No fresh Windows candidate created.
- Full strict Windows machine release chain remains required before any candidate handoff.
- NVDA_VERIFIED remains NO until Oleksii personally verifies that exact fresh candidate.
