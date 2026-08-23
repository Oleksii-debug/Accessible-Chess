# DEV5_CURRENT_STATE

UPDATED_FROM_RUN: 20260823-1301
MODE: SAFE_OVERLAP_COORDINATION / REPAIRED_STAGE1_PROMOTION
SNAPSHOT_CUTOFF: 2026-08-23T13:01:42+03:00

Prior Stage1 baseline: `0fa442330bc2bb03636ff9297512da4c29e38684`.
Promoted repaired Stage1 Product authority: `df52aeb3d99f4ae3d0089eab2882fe9b3c373dfd`.
Persistent historical exact-GREEN validation anchor: `dd9ebf9414103c805892856fe6a04706fa69039f`.
DEV4 `3e15dc2e844cb825e482317fd024795130147011` remains prior repair lineage only.

Why promotion changed: DEV1 QA-only PR #155 had a terminal pre-cutoff RED proving that `c0169ed...` leaked valid Windows drive-relative private paths. Existing DEV5 PR #151 then repaired only that sanitizer boundary, added product regressions, replayed the exact PR #155 oracle, and reached current exact head `df52aeb...`.

Exact `DEV5 Stage1 Path Privacy Repair CI` run `32627946799` is terminal SUCCESS. Linux `97166119460` and Windows `97166119501` both pass compile, focused privacy/release gates, full unittest, full pytest and diagnostic; independent current privacy oracles are replayed unchanged.

Independent compare review from `0fa442...` shows `df52aeb...` ahead 15/behind 0. Product changes are limited to path-privacy surfaces (`engine.py`, `import_registry.py`, `pgn_service.py`, new `report_paths.py`) plus release workflow/tests. No chess state, GameTree, WebView/UI or strict UIA helper changes.

Therefore `df52aeb...` is explicitly promoted for the next fresh Windows packaging/candidate attempt. This is not a merge and does not alter PR #54/frozen refs.

UIA release evidence is still unresolved separately. V2 proves unique original Move Edit and native Backspace `e9 -> e`, then stops before Ctrl+A on immediate SetValue readback. No Ctrl+A Product defect is proven. Existing `066d1e254...` and V3 `f13f20ca...` are historical QA evidence and may not be silently retargeted to the promoted Product.

Next required technical action is a new/designated exact QA harness locked to `df52aeb...`, followed by the complete uninterrupted Windows machine release chain through ZIP reopen/identity and candidate upload.

Release status: `FRESH_WINDOWS_CANDIDATE=NO`, `READY_FOR_RELEASE=NO`, `NVDA_VERIFIED=NO`.
Rejected ZIP forbidden.
