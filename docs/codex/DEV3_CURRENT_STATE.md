# DEV3 CURRENT STATE

DEV3 remains in SAFE OVERLAP release-support mode under the Stage1 release freeze. Accepted Stage1 Product authority is still `manual5/integration-20260821 @ 0fa442330bc2bb03636ff9297512da4c29e38684` until Audit/integration explicitly promotes a repaired SHA.

DEV3 exact Windows runtime evidence remains terminal GREEN in PR #142 (`32600115025 / 97097006614`) for Stockfish/runtime/analysis/clock/lifecycle on the accepted source. No DEV3-owned runtime Product defect is proven.

Accepted-source privacy evidence remains truthful: DEV3 PR #150 (`32627037392 / 97163830449`) proves engine-start private-path disclosure on accepted `0fa44233...`; DEV3 PR #148 (`32624495674 / 97157620475`) proves accepted-source PGN/ImportRegistry private-path disclosure.

DEV5 PR #151 is the active Product owner. Its current exact head is now `df52aeb3d99f4ae3d0089eab2882fe9b3c373dfd`. Exact `DEV5 Stage1 Path Privacy Repair CI` run `32627946799` is fully GREEN: Linux job `97166119460` SUCCESS and Windows job `97166119501` SUCCESS through privacy regressions, independent QA replay, full unittest, full pytest and complete diagnostic; Windows also passes focused Stage1 release contracts with LF-exact materialization.

A newly observed historical edge was correctly classified. DEV1 PR #155 run/job `32627735837 / 97165590524` proves that older repair SHA `c0169ed276fff893f90f85192416612f3b998b5a` leaked Windows drive-relative paths such as `C:Users\\PrivateUser\\Documents\\analysis.pgn`. DEV3 duplicate evidence PR #156 was immediately closed as superseded by #155. Current PR #151 head `df52aeb...` already changes `report_safe_name()` to treat any alphabetic `X:` prefix as drive-qualified and basename-redact it. Current `tests/test_stage1_release_path_privacy.py` explicitly covers both C:... and D:... drive-relative cases, and exact current Linux+Windows CI is GREEN. Thus #155 is valid historical RED against c0169ed..., not an exact-head RED against df52aeb....

Technical repair validation is GREEN, but release authority has not moved: accepted Stage1 remains `0fa44233...` until independent Audit acceptance/promotion. No fresh candidate archive is certified from PR #151 itself.

Latest completed DEV3 Full Product slice remains PR #137 (`AnalysisService` provider-result resource bounds), technically GREEN for later selective intake but not Stage1 release authority.

SAFE_OVERLAP=YES
PROVEN_STAGE1_RELEASE_PRIVACY_DEFECT=YES
PROVEN_STAGE1_ENGINE_START_PRIVACY_DEFECT=YES
PR151_CURRENT_HEAD=df52aeb3d99f4ae3d0089eab2882fe9b3c373dfd
PR151_PRIVACY_REPAIR_EXACT_CI=GREEN
DEV3_PRODUCT_PATCH_REQUIRED=NO
FRESH_WINDOWS_CANDIDATE=NO
NVDA_VERIFIED=NO
