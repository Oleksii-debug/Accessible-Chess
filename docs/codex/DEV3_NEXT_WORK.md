# DEV3 NEXT WORK

Canonical priority remains STAGE1 RELEASE FREEZE / FRESH WINDOWS CANDIDATE. Current release repair base is `manual5/integration-20260821 @ 80720e8125c59a213f278668d599040f2768d553`, which DEV3 PR #159 proved privacy-defective for Stockfish runtime diagnostics.

Highest DEV3 priority on every continuation:
1. fresh-read DEV5 PR #167 and `manual5/integration-20260821` before any work. Current PR #167 exact head is `a06c81e424c599f996662e8898c2b1cbf8ee9dbd`;
2. preserve exact current-head CI evidence: workflow `DEV5 Stage1 Stockfish Runtime Path Privacy Repair` run `32635555544` is GREEN in Windows QA oracle `97184638496`, Ubuntu QA oracle `97184638731`, Ubuntu full regression `97184638645`, and Windows full regression `97184638744`;
3. do not create a competing Stockfish/runtime privacy Product patch while PR #167 is active owner;
4. do not push further to DEV3 PR #168 while its branch has a parallel DEV3 writer. It validates a superseded DEV4 repair shape and is not exact approval evidence for PR #167 current wording;
5. preserve DEV3 PR #159 oracle unchanged. It is the independent exact-base defect proof and must be replayed unchanged after promotion;
6. wait for independent AUDIT_MASTER acceptance and authorized DEV5 promotion of `a06c81e4...` or an explicitly reviewed descendant into `manual5/integration-20260821`;
7. after promotion, identify the exact new accepted Stage1 SHA from GitHub technical truth, then replay the DEV3 PR #159 privacy oracle unchanged against that exact SHA on Ubuntu and Windows;
8. only after promoted-authority privacy GREEN may one fresh Windows candidate chain start: exact source identity -> strict UIA -> packaged Stockfish/sound -> release preflight -> ZIP reopen/hash/identity -> artifact upload;
9. never certify QA PR #160 artifacts from old `80720e8...`; that source is privacy-defective and the observed V4 run failed before Product materialization/build;
10. preserve existing DEV3 Windows runtime evidence as supporting evidence only; it does not certify a release archive;
11. classify every RED against exact SHA/logs before repair. Only a newly proven DEV3-owned Stockfish runtime, analysis, clock or engine-lifecycle defect justifies a Product patch during freeze;
12. never weaken privacy assertions, frozen-core byte/SHA assertions or native Ctrl+A/Ctrl+C assertions for GREEN.

Current terminal Full Product PR #137 remains technically GREEN for later selective DEV5 intake and is not Stage1 release authority. Parallel terminal DEV3 packages must not be reopened without a concrete regression.

SAFE_OVERLAP=YES
PR167_CURRENT_HEAD=a06c81e424c599f996662e8898c2b1cbf8ee9dbd
PR167_CURRENT_EXACT_CI=GREEN
PR167_AUDIT_PROMOTION=PENDING
DEV3_PRODUCT_PATCH_REQUIRED=NO
FRESH_WINDOWS_CANDIDATE=NO
NVDA_VERIFIED=NO
