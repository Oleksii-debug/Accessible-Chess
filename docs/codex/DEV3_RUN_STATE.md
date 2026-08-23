# DEV3 RUN STATE

RUN_ID: 20260823-promoted-stockfish-privacy-replay
STATUS: SAFE_OVERLAP / RELEASE_SUPPORT / PROMOTED_AUTHORITY_QA_PENDING
READY_FOR_INTEGRATION: NO_NEW_PRODUCT_CHANGE
OVERALL_FULL_PRODUCT_DEV3: PARTIAL

COORDINATION_BRANCH: auto/dev3-analysis-provider-bounds-20260823
TERMINAL_FULL_PRODUCT_SLICE: PR #137 / code commit 2e6e9e7767960c602d06a139948def6f9c400765 / validated head 7bcab25b54649663ba9f3094adbd14d49fdc3ced

PROMOTED_STAGE1_AUTHORITY:
- branch: manual5/integration-20260821
- previous release-hold SHA: 80720e8125c59a213f278668d599040f2768d553
- fresh exact promoted SHA: 1e9d23b034e6d347fe03c3581469a07e16037c55
- compare from 80720e8...: ahead by exactly 1 commit; Product delta confined to acs/stockfish_runtime.py

DEV3 CURRENT QA PACKAGE:
- PR #192: qa/dev3-promoted-stockfish-privacy-evidence-20260823
- exact QA head: c5371357504d6ba31b600bbbde797dab7085837f
- exact PR base: 1e9d23b034e6d347fe03c3581469a07e16037c55
- scope: QA-only test + workflow; no Product mutation
- matrices: ubuntu-24.04 and windows-2025
- gates: exact ancestry/scope, diff check, compile, existing Stockfish runtime regressions, promoted privacy oracle, focused Stage1 release/accessibility contracts
- CI: PENDING at checkpoint; no workflow run attached yet

OVERLAP DISCIPLINE:
- DEV5 remains Product owner of the accepted Stockfish runtime privacy repair.
- DEV3 does not duplicate Product implementation or move shared integration refs.
- Old QA release PR #160 remains tied to privacy-defective 80720e8... and is not an acceptable candidate source.
- PR #159 is historical defect proof; PR #176 is supporting repaired real-Stockfish evidence.

CLASSIFICATION:
SAFE_OVERLAP: YES
PROMOTION_MATERIALIZED: YES
PROMOTED_STAGE1_SHA: 1e9d23b034e6d347fe03c3581469a07e16037c55
DEV3_PRODUCT_PATCH_REQUIRED: NO
PROMOTED_PRIVACY_QA_PR: 192
PROMOTED_PRIVACY_CI: PENDING
FRESH_WINDOWS_CANDIDATE: NO
NVDA_VERIFIED: NO

NEXT: fresh-read PR #192 workflow state. If exact head c537135... is GREEN on both Ubuntu and Windows, record run/job IDs and classify promoted-authority privacy GREEN. Only then may the release owner proceed with exactly one fresh Windows candidate chain from promoted SHA 1e9d23b..., including strict UIA, packaged Stockfish/sound, release preflight, ZIP reopen/hash/identity and artifact upload. NVDA remains NO until the user personally verifies an exact fresh candidate.
