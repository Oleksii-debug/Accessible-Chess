# DEV5_CURRENT_STATE

UPDATED_FROM_RUN: 20260823-1416
MODE: ALL_LANES_RECONCILED / STAGE1_REPAIR_MACHINE_GREEN / AUDIT_PROMOTION_PENDING
SNAPSHOT_CUTOFF: 2026-08-23T11:16:04Z

Current Stage1 integration is `manual5/integration-20260821@80720e8125c59a213f278668d599040f2768d553`, but this exact SHA remains RELEASE_HOLD because independent DEV3 QA PR #159 / run `32634729467` proves three Stockfish resolver diagnostic path leaks on both Ubuntu and Windows.

The canonical minimal repair is DEV4 Product commit `1e9d23b034e6d347fe03c3581469a07e16037c55`, rooted directly at `80720e8...`. It changes `acs/stockfish_runtime.py` to use the established report-safe path contract for user-facing resolver diagnostics while preserving typed exceptions, actual resolved paths, explicit configured-path authority, packaged relative layout, provider identity and lifecycle semantics.

Independent corrected DEV4 validation PR #165 / head `e9ac9dc15b223f16914ab670358574192349995f` / run `32635517279` is terminal SUCCESS on Ubuntu and Windows. The Windows job proves existing Stockfish runtime 18/18, unchanged PR #159 oracle 3/3, current Stage1 privacy 10/10, unittest 666/666, pytest 744 + 758 subtests, SELFTEST and complete diagnostic PASS.

DEV5 PR #167 / head `a06c81e424c599f996662e8898c2b1cbf8ee9dbd` is integration staging of that exact repair, not a competing implementation. `acs/stockfish_runtime.py` is byte-identical to DEV4 Product `1e9d23b...`. DEV5 dedicated run `32635555544` is terminal SUCCESS in four Ubuntu/Windows exact-oracle/full-regression jobs.

A separate inherited old PR #151 workflow on the same DEV5 head, run `32635555545`, is RED only because its frozen allowed-path inventory rejects the expected new Stockfish runtime workflow/Product/regression paths. The Windows regression job succeeds. Classification is historical workflow topology/source-lock drift, not Product failure. Do not edit the old guard merely for GREEN.

Cross-lane non-regression:
- DEV1 PR #164 / run `32635368438` GREEN: 81/81 candidate-facing UI/accessibility/NVDA/keyboard/focus/native-menu/WebView contracts on Linux and Windows; no DEV1 Product patch required. Duplicate PR #169 is closed and must stay historical.
- DEV2 PR #166 / run `32635341589` GREEN on exact repair `1e9d23b...`: 264 canonical square/state/history/FEN/position/atomicity cases plus broader Linux/Windows regressions.
- DEV3 PR #168 is validation-only and cannot become a second Product repair lineage.

Active non-overlapping work must remain isolated:
- DEV2 RUN `20260823-1404` owns P1 fail-closed work in `acs/history.py`; DEV5 does not touch it.
- DEV-A PR #170 owns `acs/teaching_session_adapter.py`. Focused adapter/domain tests are GREEN, but current hosted run is held by stale cross-lane DEV1 WebView expectations on Ubuntu and Windows setup-python failure. Do not divert Stage1 release work into Teacher/Classroom repair.
- DEV-B is historical/stale for the current P0; DEV-C is coordination/read-only here.

PR #160/V4 targets defective `80720e8...` and is obsolete as release candidate authority. Do not fix its generated helper merely to produce a candidate from an invalid source. Packaged Move Edit SetValue/Ctrl+A/Ctrl+C remains QA-owned `C — INCONCLUSIVE`; no Product keyboard/clipboard defect is established.

Persistent Full Product exact-GREEN authority remains `dd9ebf9414103c805892856fe6a04706fa69039f` during Stage1 release freeze.

Promotion state: `1e9d23b...` is MACHINE-VALIDATED REPAIR PRODUCT and PR #167 is DEV5 INTEGRATION STAGING; independent AUDIT_MASTER acceptance is still required before Stage1 promotion/user candidate authority.

Fresh Windows candidate ZIP: NONE.
FRESH_WINDOWS_CANDIDATE=NO
READY_FOR_RELEASE=NO
NVDA_VERIFIED=NO
