# NEXT_WAVE_DIRECTIVES

DIRECTIVE_ID: DEV5-0402
REVISION: 1
SOURCE_RUN: 20260823-0402
EFFECTIVE: next fresh worker/DEV5 invocation after the 2026-08-23 04:02 Europe/Kyiv cutoff.

1. Freeze coordination intake at the invocation cutoff. For DEV1-DEV4, use only terminal evidence that existed before that cutoff; never race or partially intake current-wave touching work.
2. Preserve accepted Stage1 `0fa442330bc2bb03636ff9297512da4c29e38684`, persistent exact-GREEN `dd9ebf9414103c805892856fe6a04706fa69039f`, and DEV4 canonical repair `3e15dc2e844cb825e482317fd024795130147011` unless a later selective composition is exact-head GREEN.
3. DEV4 old `6298899... BLOCKED` classification is stale and superseded; do not regress ordering to it.
4. DEV5 touching QA branch `qa/dev5-stage1-uia-setvalue-observability-20260823` is `066d1e254c5a2776704bf1f48c580499a24b7045`, workflow-only over `ba25d7c11408901b7c327f49d1ef41d08d1b9969`. Until terminal evidence is read, SAFE OVERLAP only: no competing Product push.
5. A separate prepared V3 full-chain QA harness exists at `qa/dev5-stage1-fresh-candidate-v3-0fa442-20260823` / `f13f20ca76c8b488447d1996a635df77216397fa`. Its branch delta is exactly `.github/workflows/dev5-stage1-fresh-windows-candidate-v3.yml`; Product remains exact accepted Stage1.
6. V3's temporary `SetMoveValueEventually` repair is QA-only and fail-closed: it rewalks/reacquires the original runtime-id and requires bounded convergence. Preserve this pattern if terminal observability is GREEN. Never replace it with sleeps-only, skipped checks, relaxed provenance, xfail, or Product mutation for harness convenience.
7. Prior V2 machine evidence proves native Backspace `e9 -> e` on the original Move Edit and then fails before Ctrl+A on immediate SetValue readback. Until bounded machine evidence says otherwise, classify this as QA synchronization/observability rather than a Ctrl+A Product defect.
8. If bounded SetValue convergence is GREEN, complete V3 or equivalent full fresh Windows chain from exact `0fa442...`; do not call the ZIP a candidate until the complete chain is terminal GREEN and artifact identity is confirmed.
9. If bounded convergence itself is RED, isolate the packaged WebView/UIA state transition and produce reproducing machine proof before any Product mutation.
10. DEV1 pre-cutoff `auto/dev1-stage1-candidate-ui-evidence-20260823-0027` remains workflow-only evidence. Read terminal CI before using it as positive evidence; never treat it as Product intake authority.
11. A fresh Windows candidate requires one complete GREEN machine chain: exact source lock, frozen core identity, release contracts, WAV assets, official Stockfish, native menu structural gate, Nuitka standalone build, built-EXE diagnostic, real WebView2 startup, strict UIA interaction, packaged sound/Stockfish lifecycle, release preflight, ZIP reopen/identity and upload-candidate production.
12. PR #54 and frozen refs remain protected. Old rejected release ZIP is permanently ineligible for reuse.
13. `FRESH_WINDOWS_CANDIDATE=NO`, `READY_FOR_RELEASE=NO`, `NVDA_VERIFIED=NO` until the complete machine chain is GREEN. `NVDA_VERIFIED` changes only after the user personally verifies that exact newly produced artifact.
14. Preserve canonical core, GameTree/domain semantics, Windows-only product direction, native keyboard/menu behavior, focus origin, clipboard invariants, WebView2 boundary, accessibility names/roles/states, and existing security/privacy fail-closed behavior. Do not weaken tests.
