# DEV3 RUN STATE

RUN_ID: 20260823-1000-stage1-path-privacy-evidence
STATUS: SAFE_OVERLAP / RELEASE_SUPPORT / PROVEN_STAGE1_RELEASE_PRIVACY_DEFECT
READY_FOR_INTEGRATION: YES_FOR_PR137_ISOLATED_SLICE
OVERALL_FULL_PRODUCT_DEV3: PARTIAL

COORDINATION_BRANCH: auto/dev3-analysis-provider-bounds-20260823
DRAFT_PR: #137
TERMINAL_PRODUCT_CODE_COMMIT: 2e6e9e7767960c602d06a139948def6f9c400765
TERMINAL_VALIDATED_PRODUCT_TEST_HEAD: 7bcab25b54649663ba9f3094adbd14d49fdc3ced

CURRENT AUDIT MODE: STAGE1 RELEASE FREEZE / FRESH WINDOWS CANDIDATE PRIORITY.
ACCEPTED_STAGE1_AUTHORITY: manual5/integration-20260821 @ 0fa442330bc2bb03636ff9297512da4c29e38684

DEV3 exact accepted-source Windows runtime evidence remains GREEN in PR #142: run/job 32600115025 / 97097006614, 177/177 focused Stockfish/analysis/clock/lifecycle PASS, official Stockfish 18 real runtime PASS, one shared provider PASS, MultiPV=5 restoration PASS, packaged relative Stockfish path PASS, SELFTEST and complete diagnostic PASS.

NEW SAFE-OVERLAP RELEASE EVIDENCE:
Evidence-only PR: #148
Branch/head: qa/dev3-stage1-path-privacy-evidence-20260823 @ ee6a5da7a9f7eda8e8ecd9ce227ef5cbbf0718f5
Workflow/run/job: DEV3 Stage1 Path Privacy Evidence / 32624495674 / 97157620475
Result: FAILURE exactly at focused privacy oracle after exact accepted-parent lock, diff hygiene and compile PASS.
Focused oracle: 2 tests / 2 failures.
Observed accepted-Stage1 leaks:
- PGN existing-destination diagnostic exposes `/tmp/.../Users/PrivateUser/Documents/analysis.pgn`;
- ImportRegistry provenance diagnostic exposes `/tmp/.../Users/PrivateUser/Documents/analysis.pgn`; inspect_batch inherits through str(exc).
Classification: PROVEN_STAGE1_RELEASE_PRIVACY_DEFECT=YES. This is DEV4/DEV5 repair/integration ownership, not a DEV3 engine/runtime Product defect. No Product repair was created by DEV3.

DEV5 PR #139 still reports head ba25d7c11408901b7c327f49d1ef41d08d1b9969. Prior candidate V2 run/job 32600049016 / 97097800386 failed in QA-owned SetValue observability before native Ctrl+A; no candidate ZIP from that run. DEV3 posted the new accepted-Stage1 privacy evidence to PR #139 as comment 5384745760.

CLASSIFICATION:
- DEV3 Stockfish/runtime Product defect: NOT PROVEN.
- accepted Stage1 path privacy defect: PROVEN / RELEASE-BLOCKING until repaired and revalidated.
- SAFE_OVERLAP: YES; no competing Product, DEV4, DEV5 or QA-harness repair.
- TEST_WEAKENING: NONE.

NEXT: follow DEV4/DEV5 accepted repair promotion into Stage1, rerun PR #148 oracle unchanged, then inspect a fresh Windows candidate chain including strict UIA, packaged Stockfish/sound, release preflight, ZIP identity and artifact upload. Only a concrete DEV3-owned runtime/analysis/clock/lifecycle defect may justify a DEV3 Product patch during freeze.

FRESH_WINDOWS_CANDIDATE: NO
NVDA_VERIFIED: NO
