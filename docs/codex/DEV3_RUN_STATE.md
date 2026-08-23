# DEV3 RUN STATE

RUN_ID: 20260823-1202-stage1-privacy-current-head-reconciliation
STATUS: SAFE_OVERLAP / RELEASE_SUPPORT / CURRENT_REPAIR_GREEN_PENDING_PROMOTION
READY_FOR_INTEGRATION: YES_FOR_PR137_ISOLATED_SLICE
OVERALL_FULL_PRODUCT_DEV3: PARTIAL

COORDINATION_BRANCH: auto/dev3-analysis-provider-bounds-20260823
DRAFT_PR: #137
TERMINAL_PRODUCT_CODE_COMMIT: 2e6e9e7767960c602d06a139948def6f9c400765
TERMINAL_VALIDATED_PRODUCT_TEST_HEAD: 7bcab25b54649663ba9f3094adbd14d49fdc3ced

CURRENT AUDIT MODE: STAGE1 RELEASE FREEZE / FRESH WINDOWS CANDIDATE PRIORITY.
ACCEPTED_STAGE1_AUTHORITY: manual5/integration-20260821 @ 0fa442330bc2bb03636ff9297512da4c29e38684

DEV3 exact accepted-source Windows runtime evidence remains GREEN in PR #142: run/job 32600115025 / 97097006614, 177/177 focused Stockfish/analysis/clock/lifecycle PASS, official Stockfish 18 real runtime PASS, one shared provider PASS, MultiPV=5 restoration PASS, packaged relative Stockfish path PASS, SELFTEST and complete diagnostic PASS.

Accepted-source privacy defects remain proven by DEV3 PR #148 and PR #150. PR #150 exact accepted-source run/job 32627037392 / 97163830449: UCI recovery 3/3 PASS and engine-start privacy oracle 2/2 FAIL on accepted 0fa44233....

CURRENT DEV5 REPAIR TECHNICAL TRUTH:
PR #151 current exact head is df52aeb3d99f4ae3d0089eab2882fe9b3c373dfd, not the stale 909d8e27... or c0169ed2... heads mentioned in older reports.
Workflow: DEV5 Stage1 Path Privacy Repair CI
Run: 32627946799
Linux job 97166119460: SUCCESS through exact ancestry/diff, compile, Product-owned privacy regressions, current independent QA privacy-oracle replay, full unittest, full pytest and complete diagnostic.
Windows job 97166119501: SUCCESS through LF-exact source handling, Windows path privacy regressions, focused Stage1 release contracts, full unittest, full pytest and complete diagnostic.

DRIVE-RELATIVE EDGE RECONCILIATION:
DEV1 PR #155 run/job 32627735837 / 97165590524 truthfully FAILED on older repair SHA c0169ed276fff893f90f85192416612f3b998b5a because report_safe_name(r"C:Users\\PrivateUser\\Documents\\analysis.pgn") returned the full normalized drive-relative path instead of analysis.pgn. DEV3 briefly created PR #156 for the same question but closed it immediately as superseded by PR #155 to preserve WIP=1.
Current PR #151 head df52aeb... contains the direct repair: any alphabetic drive-qualified prefix path[1] == ':' is basename-redacted, including drive-relative forms. Current Product-owned test_stage1_release_path_privacy explicitly asserts both C:Users\\... and D:WorkstationOwner\\... basename-only behavior, and the exact current Linux+Windows CI above is GREEN. Therefore PR #155 RED is historical evidence against c0169ed..., not a blocker proven on df52aeb....

CLASSIFICATION:
- accepted Stage1 0fa44233... privacy defects: PROVEN;
- DEV5 PR #151 current repair df52aeb...: EXACT LINUX+WINDOWS GREEN including drive-relative regression coverage;
- accepted Stage1 authority has NOT yet changed;
- DEV3 Stockfish/runtime Product defect: NOT PROVEN;
- SAFE_OVERLAP: YES; no competing Product patch;
- TEST_WEAKENING: NONE.

NEXT: observe independent Audit/integration promotion. If df52aeb... or an equivalent reviewed descendant becomes the accepted Stage1 authority, replay independent DEV3 privacy oracles against that exact promoted SHA, then follow one fresh Windows candidate through strict UIA, packaged Stockfish/sound, release preflight, ZIP identity and artifact upload. Only a concrete DEV3-owned runtime/analysis/clock/lifecycle defect may justify a DEV3 Product patch during freeze.

FRESH_WINDOWS_CANDIDATE: NO
NVDA_VERIFIED: NO
