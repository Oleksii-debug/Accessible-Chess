# DEV5_RUN_STATE

RUN_ID: 20260823-1053
STARTED_LOCAL: 2026-08-23 10:53:41 Europe/Kyiv
STATUS: COMPLETE / TERMINAL
MODE: STAGE1_RELEASE_FREEZE / RELEASE_CRITICAL_PRIVACY_REPAIR / AUDIT_HANDOFF_PENDING
COORDINATOR_BRANCH: auto/dev5-coordinator-1105-20260823
SNAPSHOT_CUTOFF: 2026-08-23T10:53:41+03:00
SNAPSHOT_FILE: docs/automation/SNAPSHOT_20260823_1053.md
ACTIVE_AUDIT_DIRECTIVE: STAGE1 RELEASE FREEZE / FRESH WINDOWS CANDIDATE PRIORITY
NEXT_DEV5_DIRECTIVE: DEV5-1105 revision 1

ACCEPTED_STAGE1_SHA: 0fa442330bc2bb03636ff9297512da4c29e38684
STAGE1_PRIVACY_REPAIR_CANDIDATE_SHA: 909d8e2729e00ba5fce0f25a1520010844f9341b
PERSISTENT_GREEN_VALIDATION_SHA: dd9ebf9414103c805892856fe6a04706fa69039f
NVDA_VERIFIED: NO
FRESH_WINDOWS_CANDIDATE: NO
READY_FOR_RELEASE: NO

## Live ruling
At this run's fresh cutoff, current Audit still requires Stage1 release closure before new Full Product expansion. The accepted Stage1 authority remains `manual5/integration-20260821@0fa442330bc2bb03636ff9297512da4c29e38684`.

Independent QA changed the release risk classification. PR #148 proves private workstation-path leakage on exact accepted Stage1 `0fa442...` in PGN existing-destination diagnostics and ImportRegistry provenance mismatch/batch surfaces. Related independent QA #146/#147/#149 proves the same defect class across PGN save/concurrency diagnostics, ImportRegistry mutation/provenance/batch diagnostics, and Stockfish startup errors. Therefore accepted Stage1 `0fa442...` is machine-green for its older source/release tests but is NOT privacy-clean enough to build the final fresh candidate without a repair decision.

DEV4 current run is terminal QA-only/Product-hold and DEV-B/DEV-C do not own a competing Product repair for these exact accepted-Stage1 surfaces. DEV5 therefore used its General-Fixer role for one minimal release-critical repair from exact `0fa442...`.

## Repair candidate
Draft PR #151, branch `release/dev5-stage1-path-privacy-repair-20260823`, exact head `909d8e2729e00ba5fce0f25a1520010844f9341b`.

Changed Product surfaces are deliberately limited to:
- `acs/report_paths.py`: portable report-only sanitizer; absolute POSIX/Windows/UNC paths redact to basename; safe relative provenance remains normalized and usable;
- `acs/pgn_service.py`: sanitize read-change, existing-destination and expected-hash diagnostics only;
- `acs/import_registry.py`: sanitize source mutation/provenance diagnostics, including inherited batch error text;
- `acs/engine.py`: generic Stockfish startup failure text while preserving exception cause and internal configured path.

Added Product regression `tests/test_stage1_release_path_privacy.py` and one validation workflow. No chess state/GameTree/UI/ACSDB/Teacher/Classroom or QA-owned strict Windows helper mutation.

## Exact machine evidence
PR #151 exact repair head `909d8e27...` has terminal GREEN workflow `DEV5 Stage1 Path Privacy Repair CI`, run `32627213644`.

Linux job `97164249233` SUCCESS:
- exact ancestry/diff hygiene + compile PASS;
- Product privacy regressions 6/6 PASS;
- unchanged independent QA privacy oracles replayed PASS: PR #148 + #147 + #149 = 4 cases, plus two Stage1-compatible outer PGN cases from #146 = 2 cases;
- full unittest 659/659 PASS;
- full pytest 737 PASS + 758 subtests;
- SELFTEST PASS;
- complete WebView2 diagnostic PASS.

Windows job `97164249154` SUCCESS:
- LF-exact committed-byte materialization PASS;
- privacy regressions 6/6 PASS;
- focused Stage1 release contracts 75/75 PASS;
- full unittest 659/659 PASS;
- full pytest 737 PASS + 758 subtests;
- SELFTEST PASS;
- complete WebView2 diagnostic PASS.

Two earlier CI false-reds were validation-only and were closed without weakening any privacy assertion or Product invariant: one reusable fixture directory was made idempotent, and Windows checkout bytes were re-materialized under LF policy before frozen blob identity tests.

## Acceptance boundary
PR #151 is `MACHINE_GREEN_REPAIR_CANDIDATE`, not accepted Stage1 authority. The current Audit handoff does not yet mention `909d8e27...` or PR #151. DEV5 did not self-promote or merge it into `manual5/integration-20260821`.

Strict packaged UIA remains separately `C — INCONCLUSIVE / synchronization-observability`: prior machine evidence proves one original real Move Edit, classification A topology and native Backspace `e9 -> e`, then fails before Ctrl+A at immediate ValuePattern SetValue readback. No Ctrl+A/C Product defect is proven and QA-owned helper remains unchanged.

No fresh candidate ZIP was produced. Old rejected ZIP was not reused. PR #54/frozen refs were untouched. Full Product persistent authority remains frozen at `dd9ebf...`.

NEXT_ACTION: independent Audit readback of PR #151 exact head/diff/run. If Audit accepts/promotes the repair through the authorized Stage1 integration path, immediately start exactly one fresh strict Windows candidate chain from that newly accepted exact SHA. If Audit rejects it, fix only the concrete returned defect and rerun unchanged acceptance gates.

READY_FOR_AUDITOR_READBACK=YES
READY_FOR_RELEASE=NO
NVDA_VERIFIED=NO
