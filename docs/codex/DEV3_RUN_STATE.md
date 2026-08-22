# DEV3 RUN STATE

RUN_ID: 20260822-2002-unicode-library-search
STATUS: COMPLETE / TERMINAL
READY_FOR_INTEGRATION: YES
OVERALL_FULL_PRODUCT_DEV3: PARTIAL

BRANCH: auto/dev3-unicode-library-search-20260822
PRODUCT_PR: #105 (open/draft/evidence-only; DEV5 owns integration)
VALIDATION_PR: #106 (validation-only; do not merge into Product history)
BASE_TERMINAL_HEAD: 1dd2e9d69136a801b7943c1ee2a8b4df6d5e44f7
PRODUCT_CODE_COMMIT: 1a054f1d96cacc57104fa5fe6c0a43603c43b3ca
TEST_COMMIT: 7ae6bb44630b8261a6753a68ebce7d0e8c83dc4b
VALIDATED_PRODUCT_HEAD: 9c8a342e7dd98fee52c9776c0cb6a9b970d49296
VALIDATION_MERGE_REF: 5e73ce3df212bf178ea7e263587ee31b1ab19f0b

PACKAGE: Unicode-aware ACSDB Library/Search correctness.
- application text search now uses deterministic Unicode NFKC + casefold normalization instead of SQLite ASCII-only NOCASE behavior;
- player, event, ECO prefix, opening, and source-name filters find Cyrillic and accented-Latin case variants correctly;
- German multi-character casefold equivalence and canonically equivalent Unicode query text are covered;
- existing literal LIKE escaping for %, _, and backslash, 256-character search-resource bounds, keyset paging, provenance, strict scalar validation, exact result/source filters, and single canonical chess/application state remain unchanged.

EXACT CI EVIDENCE:
Workflow: DEV3 Full Product ACSDB CI
Run: 32586785490
Job: 97064264493
Conclusion: SUCCESS
Validated Product head: 9c8a342e7dd98fee52c9776c0cb6a9b970d49296
PR validation merge ref: 5e73ce3df212bf178ea7e263587ee31b1ab19f0b
Focused DEV3 suite: 179/179 PASS
Official Stockfish 18 bounded game-review smoke: PASS
Stockfish archive SHA-256: 536c0c2c0cf06450df0bfb5e876ef0d3119950703a8f143627f990c7b5417964 VERIFIED
Full unittest: 695/695 PASS
Full pytest: 773 passed + 641 subtests PASS
SELFTEST: PASS
ACCESSIBLE CHESS 0.4 WEBVIEW2 COMPLETE USER FLOW DIAGNOSTIC: PASS
Diff hygiene: PASS
Compile: PASS
TEST_WEAKENING: NONE
PACKAGE_DELTA_FROM_BASE_TERMINAL_HEAD: exactly 3 files (.github/workflows/dev3-full-product-acsdb-ci.yml, acs/search_service.py, tests/test_dev3_unicode_library_search.py); 3 commits; behind_by=0.

OWNERSHIP: DEV1 UI/WebView; DEV2 canonical GameTree/domain/remote-session; DEV4 PGN/ChessBase/import security; DEV5 integration/promotion. DEV3 did not mutate those lanes.
KNOWN_BLOCKER: mistake/blunder classification still awaits terminal authoritative student/actor plus fixed evaluation-perspective contract; no parallel domain model will be created.
PERFORMANCE_FOLLOWUP: Unicode-folded text clauses should receive explicit large-ACSDB query-plan/performance evidence before any index/schema optimization is proposed; do not fabricate numbers.
FRESH_WINDOWS_CANDIDATE: NO
NVDA_VERIFIED: NO
