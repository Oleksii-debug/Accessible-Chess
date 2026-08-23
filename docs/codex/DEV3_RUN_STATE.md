# DEV3 RUN STATE

RUN_ID: 20260823-1100-stage1-engine-start-privacy-followup
STATUS: SAFE_OVERLAP / RELEASE_SUPPORT / PROVEN_STAGE1_PRIVACY_DEFECT
READY_FOR_INTEGRATION: YES_FOR_PR137_ISOLATED_SLICE
OVERALL_FULL_PRODUCT_DEV3: PARTIAL

COORDINATION_BRANCH: auto/dev3-analysis-provider-bounds-20260823
DRAFT_PR: #137
TERMINAL_PRODUCT_CODE_COMMIT: 2e6e9e7767960c602d06a139948def6f9c400765
TERMINAL_VALIDATED_PRODUCT_TEST_HEAD: 7bcab25b54649663ba9f3094adbd14d49fdc3ced

CURRENT AUDIT MODE: STAGE1 RELEASE FREEZE / FRESH WINDOWS CANDIDATE PRIORITY.
ACCEPTED_STAGE1_AUTHORITY: manual5/integration-20260821 @ 0fa442330bc2bb03636ff9297512da4c29e38684

DEV3 exact accepted-source Windows runtime evidence remains GREEN in PR #142: run/job 32600115025 / 97097006614, 177/177 focused Stockfish/analysis/clock/lifecycle PASS, official Stockfish 18 real runtime PASS, one shared provider PASS, MultiPV=5 restoration PASS, packaged relative Stockfish path PASS, SELFTEST and complete diagnostic PASS.

DEV3 ACCEPTED-STAGE1 ENGINE START PRIVACY EVIDENCE:
Evidence-only PR: #150
Branch/head: qa/dev3-stage1-engine-start-privacy-evidence-20260823 @ 94fc9a8a1f708da66319d9ea63718376d339bc10
Workflow/run/job: DEV3 Stage1 Engine Start Path Privacy Evidence / 32627037392 / 97163830449
Result: FAILURE exactly at privacy oracle after exact accepted-parent/product lock, evidence-only diff gate and compile PASS.
Existing UCI recovery: 3/3 PASS.
Privacy oracle: 2/2 FAIL.
Observed accepted-Stage1 leaks:
- OSError/FileNotFoundError startup republishes the private configured executable path including PrivateUser;
- ValueError startup republishes provider detail containing the same private path.
Classification: PROVEN_STAGE1_ENGINE_START_PRIVACY_DEFECT=YES. Recovery/lifecycle behavior remains independently GREEN; this does not prove a broader Stockfish functional defect.

ACTIVE PRODUCT OWNER / SAFE OVERLAP:
DEV5 PR #151 owns the release-critical Stage1 path-privacy repair. Current head: f99146f728ace6f76606beeea6caafbb6ac940e9.
First CI run 32627055689 exposed only a reusable test-fixture mkdir collision; DEV3 classified it in PR #151 comment 5384960853 without touching Product.
Rerun 32627159257 after fixture correction:
- Linux job 97164119089: SUCCESS; Product privacy tests PASS, independent QA privacy oracles unchanged PASS, full unittest PASS, full pytest PASS, complete diagnostic PASS.
- Windows job 97164119275: privacy regressions 6/6 PASS; focused Stage1 release suite then reached 74 PASS / 1 FAIL. Sole failure is frozen-core blob identity computed from checkout working-tree bytes: stage1_release_ui_core.py observed d926aa21cbf966b193f1249d2fb811beb9c49403 instead of frozen LF blob b8586a26b9ab20c3d3ec0b0a3dbbbd53e38e94e6. PR #151 does not change that core file. Workflow sets core.autocrlf=false/core.eol=lf only after actions/checkout, so Windows CRLF materialization is the current evidence blocker. DEV3 recorded exact classification and CI-only rematerialization direction in comment 5384964048.

CLASSIFICATION:
- accepted Stage1 path privacy defect: PROVEN / RELEASE-BLOCKING until repaired authority is accepted;
- DEV5 PR #151 privacy semantics: GREEN on Linux full regression and Windows privacy surface; Windows complete release CI remains INCONCLUSIVE due checkout line-ending materialization;
- DEV3 Stockfish/runtime Product defect: NOT PROVEN;
- SAFE_OVERLAP: YES; no competing Product, DEV4, DEV5 or QA-harness repair;
- TEST_WEAKENING: NONE.

NEXT: re-read PR #151 exact head and rerun after Windows LF rematerialization. If Linux + Windows complete CI are GREEN and Audit promotes a new accepted Stage1 SHA, rerun DEV3 privacy oracles unchanged against that exact authority, then inspect the fresh Windows candidate chain through strict UIA, packaged Stockfish/sound, release preflight, ZIP identity and artifact upload. Only a concrete DEV3-owned runtime/analysis/clock/lifecycle defect may justify a DEV3 Product patch during freeze.

FRESH_WINDOWS_CANDIDATE: NO
NVDA_VERIFIED: NO
