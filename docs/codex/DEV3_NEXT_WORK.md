# DEV3 NEXT WORK

Canonical Audit remains STAGE1 RELEASE FREEZE / FRESH WINDOWS CANDIDATE PRIORITY. Accepted Stage1 source authority remains `manual5/integration-20260821 @ 0fa442330bc2bb03636ff9297512da4c29e38684` until a repaired SHA is explicitly promoted.

Highest DEV3 priority on every continuation:
1. re-read DEV5 PR #151 exact head and Audit/promotion state. Current repair head is `df52aeb3d99f4ae3d0089eab2882fe9b3c373dfd` with exact GREEN `DEV5 Stage1 Path Privacy Repair CI` run `32627946799`: Linux `97166119460` SUCCESS and Windows `97166119501` SUCCESS;
2. do not create a competing sanitizer/PGN/import/engine-start Product patch while PR #151 is active owner;
3. treat DEV1 PR #155 (`32627735837 / 97165590524`) as historical RED against older repair `c0169ed276fff893f90f85192416612f3b998b5a`, not against current `df52aeb...`; current Product regression explicitly covers C:... and D:... drive-relative basename redaction and exact current Windows/Linux CI is GREEN;
4. preserve DEV3 PR #150 accepted-source engine-start oracle unchanged: `32627037392 / 97163830449`, UCI recovery 3/3 PASS, privacy 2/2 FAIL on accepted `0fa44233...`;
5. preserve DEV3 PR #148 accepted-source PGN/ImportRegistry oracle unchanged: `32624495674 / 97157620475`;
6. only after independent Audit accepts the repaired semantics and promotes a new Stage1 authority, replay independent privacy oracles unchanged against that exact promoted SHA;
7. only after promoted-authority privacy GREEN proceed through one fresh strict Windows candidate chain: strict UIA, packaged Stockfish/sound lifecycle, release preflight, ZIP reopen/identity and artifact upload;
8. preserve DEV3 Windows runtime evidence `32600115025 / 97097006614` as supporting evidence only; it does not certify a candidate archive;
9. classify every RED against its exact SHA before repair. Only a concrete Stockfish runtime, analysis, clock or engine-lifecycle defect may justify a DEV3 Product patch during freeze;
10. do not weaken privacy assertions, frozen-core SHA assertions or native Ctrl+A/Ctrl+C assertions for GREEN.

Current terminal Full Product PR #137 remains technically GREEN for later selective DEV5 intake. Parallel DEV3 PR #134 remains terminal for final-review history identity and must not be duplicated. DEV3 PR #156 is superseded/closed; PR #155 owns the historical drive-relative evidence question.

Release success requires one fresh Windows archive from repaired exact accepted Stage1 source whose complete automated chain is GREEN and whose artifact identity is verified. Human NVDA verification comes only after that exact artifact is available.

SAFE_OVERLAP=YES
PR151_CURRENT_HEAD=df52aeb3d99f4ae3d0089eab2882fe9b3c373dfd
PR151_PRIVACY_REPAIR_EXACT_CI=GREEN
FRESH_WINDOWS_CANDIDATE=NO
NVDA_VERIFIED=NO
