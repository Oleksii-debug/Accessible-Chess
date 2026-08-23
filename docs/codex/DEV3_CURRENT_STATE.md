# DEV3 CURRENT STATE

DEV3 remains in SAFE OVERLAP release-support mode under the Stage1 release freeze. Accepted Stage1 Product authority is still `manual5/integration-20260821 @ 0fa442330bc2bb03636ff9297512da4c29e38684` until Audit/integration explicitly promotes a repaired SHA.

DEV3 exact Windows runtime evidence remains terminal GREEN in PR #142 (`32600115025 / 97097006614`) for Stockfish/runtime/analysis/clock/lifecycle on the accepted source. No DEV3-owned runtime Product defect is proven.

Evidence-only PR #150 proves accepted Stage1 engine-start path leakage: `qa/dev3-stage1-engine-start-privacy-evidence-20260823 @ 94fc9a8a1f708da66319d9ea63718376d339bc10`; `32627037392 / 97163830449`; exact source/diff/compile PASS, UCI recovery 3/3 PASS, privacy oracle 2/2 FAIL for OSError/FileNotFoundError and ValueError private executable-path disclosure. Earlier PR #148 separately proves accepted Stage1 PGN/ImportRegistry path leakage (`32624495674 / 97157620475`).

DEV5 PR #151 is the active Product owner and its current exact repair head `909d8e2729e00ba5fce0f25a1520010844f9341b` is now fully machine-GREEN. `DEV5 Stage1 Path Privacy Repair CI` run `32627213644`: Linux job `97164249233` SUCCESS through Product privacy regressions, unchanged independent QA privacy oracles, full unittest, full pytest and complete diagnostic; Windows job `97164249154` SUCCESS through LF-exact materialization, Windows privacy regressions, focused Stage1 release contracts, full unittest, full pytest and complete diagnostic. Privacy/frozen-core assertions were not weakened.

Technical repair validation is therefore GREEN, but release authority has not moved: accepted Stage1 remains `0fa44233...` until independent Audit acceptance/promotion. No fresh candidate archive is certified from PR #151 itself.

Latest completed DEV3 Full Product slice remains PR #137 (`AnalysisService` provider-result resource bounds), technically GREEN for later selective intake but not Stage1 release authority.

SAFE_OVERLAP=YES
PROVEN_STAGE1_RELEASE_PRIVACY_DEFECT=YES
PROVEN_STAGE1_ENGINE_START_PRIVACY_DEFECT=YES
PR151_PRIVACY_REPAIR_EXACT_CI=GREEN
DEV3_PRODUCT_PATCH_REQUIRED=NO
FRESH_WINDOWS_CANDIDATE=NO
NVDA_VERIFIED=NO
