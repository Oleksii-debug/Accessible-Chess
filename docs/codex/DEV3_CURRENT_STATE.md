# DEV3 CURRENT STATE

Latest DEV3 isolated backend package is terminal GREEN and READY_FOR_INTEGRATION=YES.

Branch `auto/dev3-unicode-library-search-20260822` extends prior terminal DEV3 head `1dd2e9d69136a801b7943c1ee2a8b4df6d5e44f7`. The Product change fixes the ACSDB Library/Search international-text correctness gap caused by SQLite built-in ASCII-only case folding: application filters now normalize text with Unicode NFKC + casefold on both stored values and query terms before literal LIKE matching. This covers player, event, ECO prefix, opening, and source-name filters without changing canonical chess/application state or database provenance semantics.

Product code commit: `1a054f1d96cacc57104fa5fe6c0a43603c43b3ca`.
Adversarial tests commit: `7ae6bb44630b8261a6753a68ebce7d0e8c83dc4b`.
Validated Product/test/CI head: `9c8a342e7dd98fee52c9776c0cb6a9b970d49296`.
Validation merge/evidence ref: `5e73ce3df212bf178ea7e263587ee31b1ab19f0b`.
Product PR: #105 open/draft/evidence-only.
Validation PR: #106 validation-only.

Exact machine evidence: `DEV3 Full Product ACSDB CI` run `32586785490`, job `97064264493`, SUCCESS. Focused 179/179 PASS; official Stockfish 18 bounded smoke PASS with verified archive SHA-256 `536c0c2c0cf06450df0bfb5e876ef0d3119950703a8f143627f990c7b5417964`; full unittest 695/695 PASS; pytest 773 passed + 641 subtests; SELFTEST and complete WebView2 diagnostic PASS; diff hygiene/compile PASS; no test weakening.

Package delta from prior DEV3 terminal head is exactly three files: `.github/workflows/dev3-full-product-acsdb-ci.yml`, `acs/search_service.py`, and `tests/test_dev3_unicode_library_search.py`. Existing literal `%`/`_`/backslash escaping, 256-character resource bounds, strict scalar validation, keyset paging and provenance are retained. New regressions cover Cyrillic, accented Latin, German `ß` casefold expansion, canonical-equivalent Unicode and NFKC-before-bound behavior.

Ownership preserved: DEV1 UI/WebView; DEV2 canonical GameTree/domain/remote-session; DEV4 PGN/ChessBase/import security; DEV5 selective integration/promotion. Mistake/blunder scoring remains blocked on authoritative student/actor identity plus fixed evaluation perspective. Next ACSDB work must measure Unicode-folded search on large databases before proposing schema/index changes.

FRESH_WINDOWS_CANDIDATE=NO
NVDA_VERIFIED=NO
