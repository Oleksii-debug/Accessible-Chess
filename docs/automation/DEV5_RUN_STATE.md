# DEV5_RUN_STATE

RUN_ID: 20260823-1421
STARTED_LOCAL: 2026-08-23 14:21:29 Europe/Uzhgorod
STATUS: COMPLETE
MODE: AUDIT_ACCEPTED_STAGE1_REPAIR / FRESH_WINDOWS_V5_WIP1_ACTIVE / ALL_LANES_RECONCILED
COORDINATOR_BRANCH: auto/dev5-coordinator-1421-20260823
SNAPSHOT_CUTOFF: 2026-08-23T11:21:29Z
SNAPSHOT_FILE: docs/automation/SNAPSHOT_20260823_1421.md

ACCEPTED_STAGE1_SHA: 1e9d23b034e6d347fe03c3581469a07e16037c55
PRIOR_STAGE1_SHA: 80720e8125c59a213f278668d599040f2768d553
AUDIT_ACCEPTANCE_PR: 167
AUDIT_ACCEPTANCE_COMMENT: 5385692188
PROMOTION_GATE_PR: 172
PROMOTION_GATE_RUN: 32635759733
FRESH_WINDOWS_PR: 175
FRESH_WINDOWS_HEAD: 17697b8181781c3a35f12ba522c25852d268eefc
FRESH_WINDOWS_RUN: 32636245736
FRESH_WINDOWS_JOB: 97186343167
FRESH_WINDOWS_RUN_STATUS_AT_CUTOFF: IN_PROGRESS
PERSISTENT_FULL_PRODUCT_GREEN_SHA: dd9ebf9414103c805892856fe6a04706fa69039f
FRESH_WINDOWS_CANDIDATE: NO
READY_FOR_RELEASE: NO
NVDA_VERIFIED: NO

## Current ruling
Independent AUDIT_MASTER acceptance is recorded on PR #167 for exact repair/staging head `a06c81e424c599f996662e8898c2b1cbf8ee9dbd`, accepting dedicated run `32635555544` and authorizing controlled DEV5 promotion.

Live branch identity is now definitive: `manual5/integration-20260821` is IDENTICAL to `1e9d23b034e6d347fe03c3581469a07e16037c55`; relative to `80720e8...` it is ahead exactly one commit and changes exactly one Product file, `acs/stockfish_runtime.py`. Accepted Stage1 Product authority is therefore `1e9d23b...`.

DEV5 promotion gate PR #172 / head `60866d1f82c72e416ef854600585fc9ee9e430a5` / run `32635759733` is terminal SUCCESS on Ubuntu and Windows through exact Git/source scope, unchanged DEV3 privacy oracles, current Stockfish privacy + Stage1 release regressions, full unittest, full pytest, canonical SELFTEST and complete diagnostic.

Cross-lane duplication is actively reduced:
- DEV3 PR #168 is closed as superseded evidence.
- DEV1 duplicate PR #169 remains closed. PR #173 is evidence-only and does not justify another Product implementation.
- DEV2 PR #174 targets an older intermediate repair head and is not current Stage1 authority; do not use it for promotion.
- DEV3 PR #176 is unique, non-duplicate real-engine evidence and is terminal GREEN: run `32636091171` / Windows job `97185965336`, focused 184/184, PR #159 oracle 3/3, official Stockfish 18 real shared-provider/MultiPV5/packaged-path smoke, unittest 670/670, pytest 748 + 758 subtests, SELFTEST and diagnostic PASS.
- DEV2 PR #171 is a separate narrow P1 `acs/history.py` fail-closed repair, run `32635667033` SUCCESS on Linux+Windows; hold it out of Stage1 until the active release candidate decision.
- DEV-A PR #170 remains isolated Full Product Teacher/Classroom work; do not pull it into Stage1.

Exactly one fresh release WIP exists: DEV5 QA-only PR #175 / head `17697b8181781c3a35f12ba522c25852d268eefc`, workflow run `32636245736`, job `97186343167`. At cutoff it is IN_PROGRESS at exact Windows source compile/full regressions/diagnostics/privacy oracle after setup, retained-harness identity and exact accepted-source materialization passed.

No second candidate chain, rerun, V4 repair, or QA-harness mutation is authorized while V5 is active. PR #160/V4 remains obsolete because it targets prior defective `80720e8...`.

The next release decision must come from V5 exact terminal evidence. If V5 reaches complete GREEN through strict UIA, packaged sound/Stockfish lifecycle, preflight, ZIP reopen/hash/identity and artifact upload, verify artifact identity before changing candidate status. If it fails, classify the exact first failing gate before any Product or QA change.

READY_FOR_AUDITOR_READBACK=YES
READY_FOR_RELEASE=NO
NVDA_VERIFIED=NO
