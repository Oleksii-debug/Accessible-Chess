# DEV5_NEXT_WORK

SOURCE_RUN: 20260823-0201
MODE: TERMINAL_UIA_EVIDENCE_FIRST / SAFE_OVERLAP

1. Start from exact accepted Stage1 `0fa442330bc2bb03636ff9297512da4c29e38684` and persistent exact-GREEN `dd9ebf9414103c805892856fe6a04706fa69039f`.
2. Read terminal evidence from `qa/dev5-stage1-uia-setvalue-observability-20260823` before any touching QA or Product change.
3. If the bounded SetValue probe converges, classify the prior V2 failure as QA readback/synchronization, make only the minimal strict-harness fix required for stable reacquire/observation, and rerun the complete fresh Windows release chain. Do not weaken assertions.
4. If the bounded probe does not converge, investigate the exact packaged WebView/UIA state transition first; do not jump directly to Ctrl+A or Product mutation without a reproducing machine proof.
5. DEV4 old blocker state is stale. Use repaired canonical evidence from `3e15dc2e844cb825e482317fd024795130147011` and its exact-green validation when building the next selective integration plan; do not revert to `6298899... BLOCKED`.
6. No competing Product push while any earlier DEV5 touching work remains active.
7. A fresh Windows candidate is valid only after one complete machine chain proves exact source lock, release contracts, assets, official Stockfish, native menu gate, Nuitka standalone build, built-EXE diagnostic, WebView2 startup, strict UIA interaction, packaged sound/Stockfish lifecycle, release preflight, ZIP reopen/identity and upload-candidate production.
8. PR #54/frozen refs remain untouched. Rejected ZIP must never be reused.
9. `NVDA_VERIFIED=NO` until the user personally verifies the exact fresh candidate artifact.
