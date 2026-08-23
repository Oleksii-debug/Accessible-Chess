# DEV5_NEXT_WORK

SOURCE_RUN: 20260823-0301
MODE: TERMINAL_UIA_EVIDENCE_FIRST / SAFE_OVERLAP

1. Preserve exact accepted Stage1 `0fa442330bc2bb03636ff9297512da4c29e38684`, persistent exact-GREEN `dd9ebf9414103c805892856fe6a04706fa69039f`, and DEV4 canonical repair `3e15dc2e844cb825e482317fd024795130147011`.
2. Read terminal machine evidence from `qa/dev5-stage1-uia-setvalue-observability-20260823` before any touching QA or Product change.
3. If bounded SetValue convergence succeeds, fix only strict QA synchronization/readback/reacquire behavior required for stable observation; do not weaken assertions. Then rerun the full fresh Windows release chain from exact `0fa442...`.
4. If bounded convergence fails, isolate the packaged WebView/UIA state transition first. Do not jump to Ctrl+A or Product mutation without reproducing machine proof.
5. Read terminal CI for `auto/dev1-stage1-candidate-ui-evidence-20260823-0027` before treating it as positive evidence. Its repository delta is workflow-only; it is not Product intake authority.
6. Continue SAFE OVERLAP while earlier DEV5 touching work exists. No competing Product push.
7. A valid fresh Windows candidate requires one complete GREEN machine chain: exact source lock, release contracts, WAV assets, official Stockfish, native menu structural gate, Nuitka standalone build, built-EXE diagnostic, real WebView2 startup, strict UIA interaction, packaged sound/Stockfish lifecycle, release preflight, ZIP reopen/identity and upload-candidate production.
8. PR #54/frozen refs remain untouched. Old rejected ZIP must never be reused.
9. `NVDA_VERIFIED=NO` until the user personally verifies the exact fresh candidate artifact.
