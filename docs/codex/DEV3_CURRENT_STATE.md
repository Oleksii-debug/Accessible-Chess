# DEV3 CURRENT STATE

DEV3 remains in SAFE OVERLAP release-support mode.

LIVE AUTHORITY CHANGE: `manual5/integration-20260821` has now advanced exactly one commit beyond the prior release-hold base `80720e8125c59a213f278668d599040f2768d553`. Fresh PR creation against that branch resolves the promoted authority to exact SHA `1e9d23b034e6d347fe03c3581469a07e16037c55`.

The promoted delta from `80720e8...` is confined to `acs/stockfish_runtime.py`, matching the accepted Stockfish runtime diagnostic path-privacy repair direction. DEV5 PR #167 remains the Product owner; DEV3 does not create a competing Product patch.

DEV3 created validation-only PR #192 from the exact promoted authority. PR #192 head is `c5371357504d6ba31b600bbbde797dab7085837f`; base is exact promoted SHA `1e9d23b034e6d347fe03c3581469a07e16037c55`. Scope is QA-only: one promoted privacy oracle and one Ubuntu/Windows workflow. No Product/UI/GameTree/ACSDB/PGN mutation and no test weakening.

PR #192 workflow is intended to prove QA-only ancestry/scope, compile Product+tests, run existing Stockfish runtime regressions, replay the DEV3 privacy oracle against promoted authority, and run focused Stage1 release/accessibility contracts on Ubuntu 24.04 and Windows Server 2025. At this checkpoint GitHub Actions had not yet attached a workflow run to exact head `c537135...`; CI result is therefore PENDING, not claimed.

Earlier DEV3 QA PR #159 remains the defect proof against old `80720e8...`; DEV3 real-engine PR #176 remains supporting repaired-runtime evidence. Neither substitutes for the promoted-authority replay now represented by PR #192.

SAFE_OVERLAP=YES
PROMOTED_STAGE1_SHA=1e9d23b034e6d347fe03c3581469a07e16037c55
DEV3_PROMOTED_PRIVACY_QA_PR=192
DEV3_PROMOTED_PRIVACY_QA_HEAD=c5371357504d6ba31b600bbbde797dab7085837f
DEV3_PRODUCT_PATCH_REQUIRED=NO
PROMOTED_PRIVACY_CI=PENDING
FRESH_WINDOWS_CANDIDATE=NO
NVDA_VERIFIED=NO
