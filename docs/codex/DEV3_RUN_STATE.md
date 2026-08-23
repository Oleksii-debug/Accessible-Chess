# DEV3 RUN STATE

RUN_ID: 20260823-1100-stage1-engine-start-privacy-followup
STATUS: SAFE_OVERLAP / RELEASE_SUPPORT / PRIVACY_REPAIR_GREEN_PENDING_PROMOTION
READY_FOR_INTEGRATION: YES_FOR_PR137_ISOLATED_SLICE
OVERALL_FULL_PRODUCT_DEV3: PARTIAL

COORDINATION_BRANCH: auto/dev3-analysis-provider-bounds-20260823
DRAFT_PR: #137
TERMINAL_PRODUCT_CODE_COMMIT: 2e6e9e7767960c602d06a139948def6f9c400765
TERMINAL_VALIDATED_PRODUCT_TEST_HEAD: 7bcab25b54649663ba9f3094adbd14d49fdc3ced

CURRENT AUDIT MODE: STAGE1 RELEASE FREEZE / FRESH WINDOWS CANDIDATE PRIORITY.
ACCEPTED_STAGE1_AUTHORITY: manual5/integration-20260821 @ 0fa442330bc2bb03636ff9297512da4c29e38684

DEV3 exact accepted-source Windows runtime evidence remains GREEN in PR #142: run/job 32600115025 / 97097006614, 177/177 focused Stockfish/analysis/clock/lifecycle PASS, official Stockfish 18 real runtime PASS, one shared provider PASS, MultiPV=5 restoration PASS, packaged relative Stockfish path PASS, SELFTEST and complete diagnostic PASS.

DEV3 accepted-source engine-start privacy evidence remains truthful RED in evidence-only PR #150 at head 94fc9a8a1f708da66319d9ea63718376d339bc10: workflow/run/job `DEV3 Stage1 Engine Start Path Privacy Evidence / 32627037392 / 97163830449`; source/diff/compile PASS, UCI recovery 3/3 PASS, privacy oracle 2/2 FAIL. Accepted `0fa44233...` republishes private Stockfish executable paths through both OSError/FileNotFoundError and ValueError startup failures.

ACTIVE DEV5 REPAIR NOW EXACT GREEN:
PR #151 head: 909d8e2729e00ba5fce0f25a1520010844f9341b
Workflow: DEV5 Stage1 Path Privacy Repair CI
Run: 32627213644
Linux job 97164249233: SUCCESS — ancestry/diff hygiene, compile, Product privacy regressions, unchanged independent QA privacy oracles, full unittest, full pytest, complete diagnostic PASS.
Windows job 97164249154: SUCCESS — LF-exact materialization, Windows privacy regressions, focused Stage1 release contracts, full unittest, full pytest, complete diagnostic PASS.
Two prior false-reds were CI/test-fixture issues only and were corrected without weakening assertions: reusable fixture mkdir became idempotent; Windows CI re-materializes tracked files after setting LF policy so frozen Git-byte identity is tested exactly.

CLASSIFICATION:
- current accepted Stage1 `0fa44233...` privacy defects: PROVEN;
- DEV5 PR #151 repair head `909d8e27...`: EXACT LINUX+WINDOWS GREEN, pending independent Audit acceptance/promotion;
- accepted Stage1 authority has NOT yet changed;
- DEV3 Stockfish/runtime Product defect: NOT PROVEN;
- SAFE_OVERLAP: YES; no competing Product patch;
- TEST_WEAKENING: NONE.

NEXT: independently re-read PR #151 diff/CI if ownership changes, then wait for authorized Stage1 promotion. After a new accepted SHA exists, replay DEV3 privacy oracles unchanged against that exact authority and only then follow one fresh Windows candidate through strict UIA, packaged Stockfish/sound, release preflight, ZIP identity and artifact upload. Only a concrete DEV3-owned runtime/analysis/clock/lifecycle defect may justify a DEV3 Product patch during freeze.

FRESH_WINDOWS_CANDIDATE: NO
NVDA_VERIFIED: NO
