# DEV5_RUN_STATE

RUN_ID: 20260823-1301
STARTED_LOCAL: 2026-08-23 13:01:42 Europe/Kyiv
STATUS: COMPLETE
MODE: SAFE_OVERLAP_COORDINATION / REPAIRED_STAGE1_PROMOTION
COORDINATOR_BRANCH: auto/dev5-coordinator-1301-20260823
SNAPSHOT_CUTOFF: 2026-08-23T13:01:42+03:00
SNAPSHOT_FILE: docs/automation/SNAPSHOT_20260823_1301.md

PRIOR_STAGE1_BASELINE_SHA: 0fa442330bc2bb03636ff9297512da4c29e38684
PROMOTED_REPAIRED_STAGE1_SHA: df52aeb3d99f4ae3d0089eab2882fe9b3c373dfd
PERSISTENT_GREEN_VALIDATION_SHA: dd9ebf9414103c805892856fe6a04706fa69039f
DEV4_PRIOR_REPAIR_LINEAGE_SHA: 3e15dc2e844cb825e482317fd024795130147011
PR151_EXACT_CI_RUN: 32627946799
PR151_EXACT_CI_RESULT: SUCCESS
NVDA_VERIFIED: NO
FRESH_WINDOWS_CANDIDATE: NO
READY_FOR_RELEASE: NO

## Current ruling
SAFE OVERLAP remains mandatory. This coordinator run made no competing Product or QA touching push.

Pre-cutoff DEV1 PR #155 exact head `c23c88ac21a6a9c82fad0de4aeadb695f82c5951` is terminal RED in run `32627735837`: the exact `c0169ed...` repair leaked Windows drive-relative private path provenance (`C:Users\\PrivateUser\\Documents\\analysis.pgn` -> `C:Users/PrivateUser/Documents/analysis.pgn`).

Existing DEV5 PR #151 repaired only that proven boundary. Commit `3b067dc5e049ca7656254e16ba08495a8907a6de` treats drive-qualified `X:` paths, including drive-relative forms, as private; `dcc49e45663cdbc58478f4ea3bfc957915b459cf` locks product regressions; subsequent workflow-only commits replay exact PR #155 evidence. Current exact head is `df52aeb3d99f4ae3d0089eab2882fe9b3c373dfd`.

Exact run `32627946799` is terminal SUCCESS. Linux job `97166119460` and Windows job `97166119501` both succeeded with compile, privacy/release contracts, full unittest, full pytest and diagnostic. Independent current privacy oracles are replayed unchanged; Windows includes the PR #155 drive-relative oracle.

Independent compare review `0fa442...` -> `df52aeb...` is ahead 15/behind 0. Product delta is confined to `acs/engine.py`, `acs/import_registry.py`, `acs/pgn_service.py`, `acs/report_paths.py`; remaining delta is release workflow/tests. No chess-state/GameTree/WebView/UI/strict-UIA helper mutation.

PROMOTION DECISION: `df52aeb3d99f4ae3d0089eab2882fe9b3c373dfd` is explicitly promoted as repaired Stage1 Product authority for the next fresh Windows candidate chain. This does not merge PR #151, PR #54 or frozen refs. `0fa442...` remains the prior baseline/comparison anchor.

UIA classification is unchanged: V2 proved original Move Edit + native Backspace `e9 -> e`, then failed before Ctrl+A on immediate SetValue readback. No Ctrl+A Product defect is proven. Historical QA `066d1e254...` and V3 `f13f20ca...` must not be silently retargeted.

NEXT_ACTION: one non-overlapping DEV5 release owner must create/designate a fresh QA harness locked to exact promoted Product `df52aeb...` and run the complete Windows machine candidate chain. Do not reuse old PR #139 artifact state or rejected ZIP. Only an uninterrupted GREEN chain through ZIP reopen/identity and upload may set `FRESH_WINDOWS_CANDIDATE=YES`; personal user NVDA verification is still required afterward.

READY_FOR_AUDITOR_READBACK=YES
READY_FOR_RELEASE=NO
NVDA_VERIFIED=NO
