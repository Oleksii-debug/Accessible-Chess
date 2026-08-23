# DEV3 NEXT WORK

Canonical priority remains STAGE1 RELEASE FREEZE / FRESH WINDOWS CANDIDATE. Current release-hold base is `manual5/integration-20260821 @ 80720e8125c59a213f278668d599040f2768d553`, which DEV3 PR #159 proved privacy-defective for Stockfish runtime diagnostics.

Highest DEV3 priority on every continuation:
1. fresh-read DEV5 PR #167 and `manual5/integration-20260821` before any work;
2. preserve exact Product truth: PR #167 head `a06c81e424c599f996662e8898c2b1cbf8ee9dbd` is full Linux+Windows CI GREEN and independently AUDIT_MASTER ACCEPTED for controlled DEV5 promotion;
3. do not create a competing Stockfish/runtime privacy Product patch and do not perform DEV5 promotion from DEV3;
4. preserve validation-only PR #176 exact GREEN: run `32636091171`, Windows job `97185965336`, focused 184/184, unchanged PR #159 oracle 3/3, real official Stockfish 18 shared-provider/MultiPV restoration/engine-play/packaged-path PASS, full unittest 670/670, pytest 748 + 758 subtests, selftest and complete diagnostic PASS;
5. treat PR #176 as supporting runtime evidence only, never as a candidate ZIP or NVDA proof;
6. preserve DEV3 PR #159 oracle unchanged. It is the independent defect oracle that must be replayed after promotion;
7. as soon as DEV5 promotion materializes, identify the exact new accepted Stage1 SHA from GitHub technical truth and replay PR #159 oracle unchanged against that exact SHA on Ubuntu and Windows;
8. only after promoted-authority privacy GREEN may one fresh Windows candidate chain start: exact source identity -> strict UIA -> packaged Stockfish/sound -> release preflight -> ZIP reopen/hash/identity -> artifact upload;
9. never certify QA PR #160 artifacts from old `80720e8...`;
10. PR #168 is closed/superseded historical validation; do not reopen it;
11. classify every RED against exact SHA/logs before repair. Only a newly proven DEV3-owned Stockfish runtime, analysis, clock or engine-lifecycle defect justifies a Product patch during freeze;
12. never weaken privacy assertions, frozen-core byte/SHA assertions or native Ctrl+A/Ctrl+C assertions for GREEN.

Current terminal Full Product PR #137 remains technically GREEN for later selective DEV5 intake and is not Stage1 release authority.

SAFE_OVERLAP=YES
PR167_CURRENT_HEAD=a06c81e424c599f996662e8898c2b1cbf8ee9dbd
PR167_AUDIT_ACCEPTED=YES
PR167_PROMOTION_MATERIALIZED=NO_AT_LAST_READ
REAL_STOCKFISH18_REPAIR_EVIDENCE=GREEN
DEV3_PRODUCT_PATCH_REQUIRED=NO
FRESH_WINDOWS_CANDIDATE=NO
NVDA_VERIFIED=NO
