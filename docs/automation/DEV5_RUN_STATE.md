# DEV5_RUN_STATE

RUN_ID: 20260823-1503
STARTED_LOCAL: 2026-08-23 15:03 Europe/Kyiv
STATUS: COMPLETE
MODE: CONTROLLED_COMBINED_VALIDATION_GREEN / RELEASE_HOLD_FEN_P1 / V5_FOCUS_C_INCONCLUSIVE
COORDINATOR_BRANCH: auto/dev5-coordinator-1503-20260823
SNAPSHOT_CUTOFF: 2026-08-23T12:03:00Z
SNAPSHOT_FILE: docs/automation/SNAPSHOT_20260823_1503.md

ACCEPTED_STAGE1_AT_CUTOFF: 1e9d23b034e6d347fe03c3581469a07e16037c55
ACCEPTED_HISTORY_REPAIR: 45956b38ce6d1ed42d937fdda0124569b8e60b54
INTERMEDIATE_COMBINED_PR: 195
INTERMEDIATE_COMBINED_HEAD: 5e8ca72f7dd552ee151ebd5b85c52148004ac307
INTERMEDIATE_COMBINED_RUN: 32638839597
INTERMEDIATE_COMBINED_UBUNTU_JOB: 97192655470
INTERMEDIATE_COMBINED_WINDOWS_JOB: 97192655352
INTERMEDIATE_COMBINED_RESULT: SUCCESS
V5_RUN: 32636245736
V5_RESULT: FAILURE / OBSOLETE_SOURCE / NO_ZIP
FEN_P1_STATUS_AT_CUTOFF: PROVEN / DEV2_OWNED / NOT_YET_IN_FINAL_STAGE1
PERSISTENT_FULL_PRODUCT_GREEN_SHA: dd9ebf9414103c805892856fe6a04706fa69039f
FRESH_WINDOWS_CANDIDATE: NO
READY_FOR_RELEASE: NO
NVDA_VERIFIED: NO

## Current ruling
Pre-cutoff AUDIT_MASTER superseded the prior V5-only release route. It independently accepted DEV2 history scalar fail-closed repair `45956b38...`, required final Stage1 to contain both accepted Stockfish privacy and history repairs, and separately proved a P1 oversized FEN-counter error-surface defect routed to DEV2. Therefore V5 source `1e9d23b...` became obsolete as final candidate authority before this cutoff.

V5 run `32636245736` is terminal FAILURE. It nevertheless resolves the historical native keyboard uncertainty: packaged Move Edit native Ctrl+A selection passed and native Ctrl+C copied exact `e9`. The first strict failure moved to post-submit board focus continuity. The retained QA helper kept the pre-rerender UIA square element while Product rerendered the semantic 64-cell board; the target then had empty AutomationId/Name. Final focus was Move Edit. This is C / INCONCLUSIVE between stale-target observability and Product focus timing, not a proven Product B defect. No Product focus mutation is authorized from that run alone.

Following the pre-cutoff Audit route, DEV5 reused existing no-duplication combined branch and opened draft PR #195. Product content is only the accepted Stockfish resolver privacy repair and accepted history scalar fail-closed repair. Two workflow-only validation corrections were made: exact PR-head checkout (`63b3cd...`) and accepted history blob pin (`5e8ca72...`).

Dedicated `DEV5 Stage1 Combined Repair Validation` run `32638839597` is terminal SUCCESS on exact head `5e8ca72f7dd552ee151ebd5b85c52148004ac307` on Ubuntu and Windows. Both pass exact ancestry/blob/scope gates, Product repair regressions 44/44, unchanged PR #159 oracle 3/3, privacy/history stress 23 + 11 subtests, focused Stage1 release contracts 80/80, unittest 673/673, pytest 751 + 758 subtests, SELFTEST and complete WebView2 diagnostic.

This establishes INTERMEDIATE_COMBINED_GREEN only. PR #195 remains DRAFT / DO NOT MERGE OR PROMOTE because the pre-cutoff FEN P1 is absent from this source. No V6 or human candidate may start from `5e8ca72...`.

Post-cutoff FEN/focus branches are quarantined and must be reread under the next immutable cutoff before any selective intake. Persistent Full Product remains frozen.

READY_FOR_AUDITOR_READBACK=YES
READY_FOR_RELEASE=NO
NVDA_VERIFIED=NO
