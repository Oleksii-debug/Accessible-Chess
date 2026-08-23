# NEXT_WAVE_DIRECTIVES

DIRECTIVE_ID: DEV5-1105
REVISION: 1
SOURCE_RUN: 20260823-1053
EFFECTIVE: next fresh DEV5/Audit invocation after the 2026-08-23 10:53:41 Europe/Kyiv cutoff.

1. Stage1 release freeze remains active. Full Product persistent authority stays `dd9ebf9414103c805892856fe6a04706fa69039f`; do not advance it before a fresh Stage1 candidate decision.
2. Current accepted Stage1 remains `manual5/integration-20260821@0fa442330bc2bb03636ff9297512da4c29e38684` until independent Audit promotion. Do not silently retarget accepted authority.
3. Exact accepted Stage1 has a proven release privacy defect: QA PR #148 fails on private absolute-path disclosure. Related QA #146/#147/#149 proves the same class across PGN diagnostics, ImportRegistry diagnostics/batch and Stockfish startup errors.
4. DEV5 repair PR #151 exact head `909d8e2729e00ba5fce0f25a1520010844f9341b` is the current machine-green repair candidate. It descends directly from `0fa442...` and changes only `acs/report_paths.py`, diagnostic rendering in `acs/pgn_service.py`, `acs/import_registry.py`, one startup-error line in `acs/engine.py`, plus a regression and CI workflow.
5. Run `32627213644` is terminal SUCCESS. Linux job `97164249233`: privacy 6/6, independent QA replay PASS, unittest 659/659, pytest 737 + 758 subtests, SELFTEST + diagnostic PASS. Windows job `97164249154`: privacy 6/6, Stage1 release contracts 75/75, unittest 659/659, pytest 737 + 758 subtests, SELFTEST + diagnostic PASS.
6. The first two PR #151 workflow failures were validation-only false-reds: fixture directory idempotence and CRLF checkout materialization. They were fixed without changing privacy assertions, exception classes, chess semantics or QA oracles.
7. Classification is `MACHINE_GREEN_REPAIR_CANDIDATE / AUDIT_ACCEPTANCE_PENDING`. AUDIT_MASTER must independently inspect exact PR #151 SHA/diff/run before any Stage1 promotion. DEV5 must not self-accept its own Product repair.
8. If accepted, promote only the minimal repair through the authorized Stage1 integration path and record the exact resulting accepted SHA. Never wholesale merge validation history.
9. Immediately after acceptance, run exactly one current fresh Windows candidate chain from that exact accepted SHA. Required machine sequence: source identity/frozen blobs; release/focused/full tests; WAV; official Stockfish 18; native menu; Nuitka EXE; EXE diagnostic/real WebView2; QA-owned strict packaged UIA; packaged sound/Stockfish lifecycle; release preflight; ZIP reopen/identity; candidate upload.
10. Strict UIA current classification remains `C — INCONCLUSIVE / synchronization-observability`: one original Move Edit and native Backspace `e9 -> e` are proven, but previous chain failed before Ctrl+A on immediate SetValue readback. Do not call this a Ctrl+A/C Product defect. Do not modify QA-owned helper without Audit ownership transfer.
11. If strict UIA is C again, gather bounded convergence/reacquire evidence. If it is B, repair only that exact machine-proven Product defect and re-establish accepted source before rebuilding.
12. If PR #151 is rejected, repair only the concrete Audit return and replay unchanged privacy oracles + full Linux/Windows regression gates.
13. No old/rejected candidate ZIP may be reused. PR #139 outputs are not a fresh candidate authority. PR #54/frozen refs remain untouched.
14. `FRESH_WINDOWS_CANDIDATE=NO`, `READY_FOR_RELEASE=NO`, `NVDA_VERIFIED=NO` now. Only a complete machine-GREEN fresh artifact changes candidate status; only Oleksii's personal test changes `NVDA_VERIFIED`.
