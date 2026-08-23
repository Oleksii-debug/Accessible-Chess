# DEV3 RUN STATE

RUN_ID: 20260823-stage1-stockfish-runtime-privacy-real-engine
STATUS: SAFE_OVERLAP / RELEASE_SUPPORT / AUDIT_ACCEPTED_REPAIR_PENDING_DEV5_PROMOTION
READY_FOR_INTEGRATION: YES_FOR_PR137_ISOLATED_SLICE
OVERALL_FULL_PRODUCT_DEV3: PARTIAL

COORDINATION_BRANCH: auto/dev3-analysis-provider-bounds-20260823
DRAFT_PR: #137
TERMINAL_PRODUCT_CODE_COMMIT: 2e6e9e7767960c602d06a139948def6f9c400765
TERMINAL_VALIDATED_PRODUCT_TEST_HEAD: 7bcab25b54649663ba9f3094adbd14d49fdc3ced
TERMINAL_PRODUCT_CI: DEV3 Analysis Provider Bounds CI 32599676493 / 97095971890 SUCCESS

STAGE1 RELEASE HOLD BASE: manual5/integration-20260821 @ 80720e8125c59a213f278668d599040f2768d553

RELEASE DEFECT EVIDENCE:
- DEV3 QA PR #159 / run 32634729467 proves the StockfishRuntime resolver diagnostic path-privacy defect on exact 80720e8... on Ubuntu and Windows while the pre-existing Stockfish runtime suite remains 18/18 PASS.
- This proves diagnostic path disclosure, not a Stockfish runtime correctness defect.

ACTIVE PRODUCT OWNER:
- DEV5 PR #167 exact head: a06c81e424c599f996662e8898c2b1cbf8ee9dbd; base SHA still 80720e8125c59a213f278668d599040f2768d553 at the latest live read.
- PR #167 exact workflow run 32635555544 is fully GREEN on Ubuntu and Windows across exact privacy oracles and full regressions.
- Independent AUDIT_MASTER has ACCEPTED exact a06c81e4... and authorized DEV5 controlled minimal promotion. DEV3 does not own promotion.

DEV3 REAL-ENGINE VALIDATION:
- validation-only PR #176: qa/dev3-real-stockfish-privacy-repair-20260823 @ 1cdedc4cb66778885aafbc1bd3a4600d6c14d306.
- exact workflow DEV3 Real Stockfish Privacy Repair Evidence run 32636091171 / Windows job 97185965336: SUCCESS.
- exact audit-accepted Product lock and validation-only scope PASS.
- focused engine/runtime/privacy 184/184 PASS; unchanged PR #159 privacy oracle 3/3 PASS.
- official Stockfish 18 Windows binary executed; observed SHA-256 9bde420202717ce083412027fbfb8c5c935b537591d712be8a8a8bae92f6e8d6 (observed only, not claimed against a published checksum).
- real StockfishRuntime -> AnalysisService -> EnginePlayService shared-provider identity PASS; MultiPV=5 before play and restored after play PASS; legal real engine move PASS; packaged relative engine path PASS.
- full unittest 670/670 PASS; pytest 748 passed + 758 subtests; canonical selftest and complete WebView2 diagnostic PASS.
- no Product mutation and no test weakening/skip/xfail.

OVERLAP DISCIPLINE:
- DEV3 PR #168 is closed/superseded historical validation and is not current release approval evidence.
- QA PR #160 is tied to privacy-defective 80720e8... and cannot yield an acceptable candidate.
- No fresh Windows release archive is certified.

CLASSIFICATION:
SAFE_OVERLAP: YES
DEV3_PRODUCT_PATCH_REQUIRED: NO
PR167_AUDIT_ACCEPTED: YES
PR167_DEV5_PROMOTION_MATERIALIZED: NO_AT_LAST_READ
REAL_STOCKFISH18_REPAIR_EVIDENCE: GREEN
FRESH_WINDOWS_CANDIDATE: NO
NVDA_VERIFIED: NO

NEXT: fresh-read PR #167 and manual5/integration-20260821. Once DEV5 promotion materializes, record the exact new accepted Stage1 SHA and replay the unchanged DEV3 PR #159 privacy oracle against that exact promoted SHA on Ubuntu and Windows. Only after promoted-authority privacy GREEN may exactly one fresh Windows candidate chain proceed through strict UIA, packaged Stockfish/sound, release preflight, ZIP reopen/hash/identity and artifact upload. Open DEV3 Product code only for a newly proven runtime/analysis/clock/lifecycle defect.
