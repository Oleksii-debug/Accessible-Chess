# DEV3 CURRENT STATE

DEV3 remains in SAFE OVERLAP release-support mode under Stage1 release freeze. The release-hold base is still `manual5/integration-20260821 @ 80720e8125c59a213f278668d599040f2768d553` at the latest live PR-base read.

DEV3 QA PR #159 independently proved the `StockfishRuntime.resolve_stockfish_path()` diagnostic path-privacy defect on exact `80720e8...`: run `32634729467` failed the 3-case privacy oracle on Ubuntu and Windows while the pre-existing Stockfish runtime regressions remained 18/18 PASS. This is path disclosure, not a runtime-correctness failure.

DEV5 PR #167 owns the Product repair at exact head `a06c81e424c599f996662e8898c2b1cbf8ee9dbd`. Exact workflow `DEV5 Stage1 Stockfish Runtime Path Privacy Repair`, run `32635555544`, is fully GREEN on Ubuntu and Windows across exact QA-oracle and full-regression jobs. Independent AUDIT_MASTER has accepted exact `a06c81e4...` and authorized controlled DEV5 promotion. Promotion has not yet materialized because PR #167 still reports base SHA `80720e8...`; DEV3 does not move that integration ref.

DEV3 added unique real-engine evidence without Product mutation in validation-only PR #176. Exact head `1cdedc4cb66778885aafbc1bd3a4600d6c14d306`; workflow `DEV3 Real Stockfish Privacy Repair Evidence`, run `32636091171`, Windows job `97185965336`, SUCCESS. Focused engine/runtime/privacy regressions are 184/184 PASS, unchanged PR #159 privacy oracle 3/3 PASS, official Stockfish 18 executed against the repaired runtime, shared provider identity and MultiPV=5 restoration passed, legal engine play passed, packaged relative Stockfish path passed, full unittest 670/670 PASS, pytest 748 passed + 758 subtests, canonical selftest and complete WebView2 diagnostic PASS. Observed Stockfish executable SHA-256: `9bde420202717ce083412027fbfb8c5c935b537591d712be8a8a8bae92f6e8d6`; this is an observed hash only.

PR #176 is supporting Windows runtime evidence, not a release ZIP and not NVDA verification. DEV3 PR #168 is closed/superseded historical validation. QA release PR #160 remains tied to privacy-defective `80720e8...` and cannot yield an acceptable human candidate.

The terminal DEV3 Full Product slice remains PR #137 (`AnalysisService` provider-result resource bounds), technically GREEN for later selective intake and separate from Stage1 release authority.

SAFE_OVERLAP=YES
PROVEN_STAGE1_STOCKFISH_RUNTIME_PATH_PRIVACY_DEFECT=YES
PR167_CURRENT_HEAD=a06c81e424c599f996662e8898c2b1cbf8ee9dbd
PR167_AUDIT_ACCEPTED=YES
PR167_PROMOTION_MATERIALIZED=NO_AT_LAST_READ
REAL_STOCKFISH18_REPAIR_EVIDENCE=GREEN
DEV3_PRODUCT_PATCH_REQUIRED=NO
FRESH_WINDOWS_CANDIDATE=NO
NVDA_VERIFIED=NO
