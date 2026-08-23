# DEV5_NEXT_WORK

SOURCE_RUN: 20260823-1053
MODE: AUDIT_ACCEPTANCE_FIRST / STAGE1_FRESH_CANDIDATE_ONLY

1. Preserve accepted Stage1 `0fa442330bc2bb03636ff9297512da4c29e38684` until independent Audit explicitly accepts/promotes the repair candidate. Preserve persistent Full Product `dd9ebf9414103c805892856fe6a04706fa69039f`; no Full Product expansion during release freeze.
2. Treat PR #151 `release/dev5-stage1-path-privacy-repair-20260823@909d8e2729e00ba5fce0f25a1520010844f9341b` as `MACHINE_GREEN_REPAIR_CANDIDATE`, not current accepted Stage1 authority.
3. Audit exact PR #151 diff and run `32627213644`. Required evidence is already terminal GREEN on both Linux and Windows: privacy 6/6, independent QA replay, Stage1 release contracts 75/75, unittest 659/659, pytest 737 + 758 subtests, SELFTEST and complete diagnostic.
4. If Audit accepts the repair, promote only through the authorized Stage1 integration path. Do not merge validation/evidence history wholesale. Record the exact newly accepted SHA before any build.
5. Then start exactly one WIP fresh Windows release chain from the exact newly accepted SHA: source lock/frozen identity -> focused/full regressions -> real WAV -> official Stockfish 18 -> native menu -> standalone EXE -> built-EXE diagnostic/real WebView2 -> QA-owned strict UIA -> packaged sound/Stockfish lifecycle -> release preflight -> ZIP reopen/identity -> candidate upload.
6. Keep the QA-owned strict packaged UIA helper unchanged unless Audit explicitly transfers ownership. Current SetValue/Ctrl+A issue remains `C — INCONCLUSIVE / synchronization-observability`; do not patch Product or declare Ctrl+A/C defect without a B-class machine proof.
7. If strict UIA remains C on the repaired source, continue bounded observability/reacquire evidence, not assertion weakening. If it returns B, repair only the exact machine-proven Product defect and restart the candidate chain from the new accepted repair.
8. If Audit rejects PR #151, fix only the concrete returned issue and replay the same independent privacy oracles plus full Linux/Windows regression gates. Do not broaden scope speculatively.
9. Do not reuse PR #139 output or any old human-rejected ZIP. A candidate exists only after the complete current machine chain is GREEN and artifact identity is verified.
10. PR #54/frozen refs remain protected. `NVDA_VERIFIED=NO` until Oleksii personally verifies the exact fresh artifact.
