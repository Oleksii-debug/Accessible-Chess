# NEXT_WAVE_DIRECTIVES

DIRECTIVE_ID: DEV5-0703
REVISION: 1
SOURCE_RUN: 20260823-0703
EFFECTIVE: next fresh worker/DEV5 invocation after the 2026-08-23 07:03 Europe/Kyiv cutoff.

1. Freeze coordination intake at the invocation cutoff. For DEV1-DEV4, use only terminal evidence that existed before that cutoff; never race or partially intake current-wave touching work.
2. Preserve accepted Stage1 `0fa442330bc2bb03636ff9297512da4c29e38684`, persistent exact-GREEN `dd9ebf9414103c805892856fe6a04706fa69039f`, and DEV4 canonical repair `3e15dc2e844cb825e482317fd024795130147011` unless a later selective composition is exact-head GREEN.
3. DEV4 old `6298899... BLOCKED` classification is stale and superseded; do not regress ordering to it.
4. DEV5 touching QA branch `qa/dev5-stage1-uia-setvalue-observability-20260823` remains `066d1e254c5a2776704bf1f48c580499a24b7045`. Connected Actions readback exposed no run for that exact SHA at the 0703 cutoff. Until terminal evidence is read, SAFE OVERLAP only: no competing Product push.
5. Prepared V3 full-chain QA harness remains `qa/dev5-stage1-fresh-candidate-v3-0fa442-20260823` / `f13f20ca76c8b488447d1996a635df77216397fa`. Connected Actions readback exposed no run for that exact SHA either. Treat it as QA infrastructure, not positive release evidence.
6. V3 SetValue synchronization remains QA-only and fail-closed: bounded convergence, rewalk/reacquire, original runtime-id provenance. Never replace it with sleeps-only, skipped checks, relaxed provenance, xfail, or Product mutation for harness convenience.
7. Prior V2 machine evidence proves native Backspace `e9 -> e` on the original Move Edit and then fails before Ctrl+A on immediate SetValue readback. Until bounded machine evidence says otherwise, classify this as QA synchronization/observability rather than a Ctrl+A Product defect.
8. If bounded SetValue convergence is GREEN, complete V3 or equivalent full fresh Windows chain from exact `0fa442...`; do not call the ZIP a candidate until the complete chain is terminal GREEN and artifact identity is confirmed.
9. If bounded convergence itself is RED, isolate the packaged WebView/UIA state transition and produce reproducing machine proof before any Product mutation.
10. DEV2 pre-cutoff PR #140 / evidence head `06d610e90731d8b987bd6def02e0d7e39748808e` is validation-only and explicitly DO NOT MERGE. Canonical DEV2 Product base is `b4dcca10136bf014e7fd326e96cd0bcdfe285af1`. Keep it out of Stage1 release composition; consider only for later selective Full Product intake after release freeze.
11. DEV3 pre-cutoff PR #137 / final head `b97c3c14255bf37033cb644bc544e3bc3cf1095b` is terminal technical GREEN for isolated AnalysisService provider-result bounds. CI `32599676493/97095971890` and rerun `32599905359/97096518152` are SUCCESS. It is later selective integration backlog, not Stage1 release authority.
12. DEV3 pre-cutoff engine history-node identity-bound slice on `auto/dev3-engine-history-id-bounds-20260823` is terminal GREEN: Product `1caea4ea3c3c5370edf1ef2f9817d73829ae1adb`, validated `43ca7f96e6222401d9d432beb5d3837fd36dbea2`, CI `32599495584/97095538276` SUCCESS, focused 94/94, unittest 722/722, pytest 800 + 657 subtests, SELFTEST/diagnostic/diff/compile PASS. Keep it in later selective Full Product backlog; do not contaminate Stage1 release freeze.
13. DEV1 pre-cutoff `auto/dev1-stage1-candidate-ui-evidence-20260823-0027` remains workflow-only evidence over accepted Stage1. Read terminal CI before using it as positive evidence; never treat it as Product intake authority.
14. A fresh Windows candidate requires one complete GREEN machine chain: exact source lock, frozen core identity, release contracts, WAV assets, official Stockfish, native menu structural gate, Nuitka standalone build, built-EXE diagnostic, real WebView2 startup, strict UIA interaction, packaged sound/Stockfish lifecycle, release preflight, ZIP reopen/identity, and upload-candidate production.
15. PR #54 and frozen refs remain protected. Old rejected release ZIP is permanently ineligible for reuse.
16. `FRESH_WINDOWS_CANDIDATE=NO`, `READY_FOR_RELEASE=NO`, `NVDA_VERIFIED=NO` until the complete machine chain is GREEN. `NVDA_VERIFIED` changes only after the user personally verifies that exact newly produced artifact.
17. Preserve canonical core, GameTree/domain semantics, Windows-only product direction, native keyboard/menu behavior, focus origin, clipboard invariants, WebView2 boundary, accessibility names/roles/states, and existing security/privacy fail-closed behavior. Do not weaken tests.
