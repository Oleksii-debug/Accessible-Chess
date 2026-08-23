# NEXT_WAVE_DIRECTIVES

DIRECTIVE_ID: DEV5-1301
REVISION: 1
SOURCE_RUN: 20260823-1301
EFFECTIVE: next worker/DEV5 invocation after 2026-08-23 13:01:42 Europe/Kyiv cutoff.

1. Freeze DEV1-DEV4 coordination intake at this cutoff. Use only terminal evidence that existed before it; do not race post-cutoff touching work.
2. Repaired Stage1 Product authority is explicitly promoted to `df52aeb3d99f4ae3d0089eab2882fe9b3c373dfd`. Prior Stage1 baseline `0fa442330bc2bb03636ff9297512da4c29e38684` remains the historical comparison anchor only.
3. Promotion evidence: DEV1 PR #155 exact head `c23c88ac21a6a9c82fad0de4aeadb695f82c5951` terminal RED proved the drive-relative privacy gap on `c0169ed...`; DEV5 PR #151 then repaired that exact boundary and replayed the oracle unchanged.
4. Exact PR #151 head `df52aeb...` has terminal `DEV5 Stage1 Path Privacy Repair CI` SUCCESS in run `32627946799`; Linux `97166119460` SUCCESS and Windows `97166119501` SUCCESS. Both include compile, focused gates, full unittest, full pytest and diagnostic; independent current privacy oracles are replayed unchanged.
5. Independent compare `0fa442...` -> `df52aeb...` is ahead 15/behind 0. Product delta is limited to `acs/engine.py`, `acs/import_registry.py`, `acs/pgn_service.py`, new `acs/report_paths.py`; remaining changes are release workflow/tests. No chess state, GameTree, WebView/UI or strict UIA helper mutation.
6. Do not merge PR #151 merely for convenience. PR #54 and frozen refs remain protected.
7. SAFE OVERLAP remains mandatory whenever another DEV5/worker owns touching release work. Do not create a competing Product or QA push while such work is active.
8. Next release owner must create/designate one fresh QA harness explicitly locked to Product `df52aeb...` and record the exact harness SHA. Do not silently retarget historical V3 `f13f20ca...`, observability `066d1e254...`, PR #139 or any old artifact state.
9. Candidate validity requires one uninterrupted terminal GREEN Windows chain: exact source lock; frozen-core identity; release contracts; WAV assets; official Stockfish; native-menu structural gate; Nuitka standalone; built-EXE diagnostic; real WebView2 startup; strict UIA interaction; packaged sound/Stockfish lifecycle; release preflight; ZIP reopen/identity; candidate upload.
10. UIA classification remains strict: V2 proved unique original Move Edit and native Backspace `e9 -> e`, then stopped before Ctrl+A on immediate SetValue readback. No Ctrl+A Product defect is proven. Bounded observability/reacquire may be used only while preserving original element/runtime identity and fail-closed assertions.
11. If a new fresh chain fails before Ctrl+A, isolate that exact transition. Do not mutate Product based on an inferred later failure.
12. If the full fresh chain is GREEN, record exact Product SHA, exact QA harness SHA, run/job IDs, artifact ID, hash and reopened ZIP identity before setting `FRESH_WINDOWS_CANDIDATE=YES`.
13. `READY_FOR_RELEASE` remains NO until all gates for that exact artifact are satisfied. `NVDA_VERIFIED` remains NO until the user personally verifies that exact candidate with NVDA.
14. Rejected/old ZIP must not be reused.
15. DEV2/DEV3 Full Product slices remain later selective backlog; do not contaminate Stage1 release freeze.
16. DEV4 `3e15dc2e...` remains prior lineage only; obsolete privacy conclusions and obsolete `909d8e...` false-GREEN must not be revived.
17. Preserve canonical core, Windows-only direction, native keyboard/menu behavior, focus origin, clipboard invariants, WebView2 boundary, accessibility roles/names/states and fail-closed privacy/security contracts.
18. No force-push shared history. No skips, xfails or weakened assertions.
19. `AGENTS.md` and `docs/codex/*` remain absent on live default branch at this cutoff. Use live GitHub SHA/diff/tests/CI plus versioned `docs/automation/*` unless those files later appear and are verified.
