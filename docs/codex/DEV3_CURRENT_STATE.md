# DEV3 CURRENT STATE

Latest DEV3 package is terminal GREEN evidence for large-library Unicode ACSDB search. It intentionally changes no Product behavior or schema, so this evidence package itself is not an integration candidate. The inherited Unicode correctness package remains PR #105 / validated Product head `9c8a342e7dd98fee52c9776c0cb6a9b970d49296`, READY_FOR_INTEGRATION=YES.

Evidence branch: `auto/dev3-unicode-search-performance-evidence-20260822`.
Evidence PR: #107, open/draft/evidence-only.
Validation PR: #108, validation-only.
Probe commit: `19cc573f7588f13d6d988726c52d210b70e6e7eb`.
Exact GREEN validation head: `06bb37a119f31d92dea93f537bc580facf5eebb2`.
Validation merge ref: `770811ccaaeb694ca95dacf9b558b9efb0a06edf`.

Exact machine evidence: `DEV3 Full Product ACSDB CI` run `32589798970`, job `97071708911`, SUCCESS. Focused 179/179 PASS; official Stockfish 18 bounded smoke PASS with verified archive SHA-256 `536c0c2c0cf06450df0bfb5e876ef0d3119950703a8f143627f990c7b5417964`; full unittest 695/695 PASS; pytest 773 passed + 641 subtests; SELFTEST and complete WebView2 diagnostic PASS; diff hygiene/compile PASS; no test weakening.

The new public-service probe seeds 100,000 ACSDB games and captures exact traced SELECTs, `EXPLAIN QUERY PLAN`, and five repeated timings per case. On the Ubuntu 24.04 / CPython 3.12.14 Actions runner, first-page Unicode-folded no-hit queries performed full `SCAN g`: player median 145.941 ms, event 68.261 ms, ECO prefix 50.060 ms. A common player hit with `limit=50` still reported `SCAN g` but terminated early at median 1.190 ms. A keyset-tail no-hit after game 90,000 used `SEARCH g USING INTEGER PRIMARY KEY (rowid>?)` and median 16.432 ms. No tested query materialized a temporary ORDER BY B-tree.

This is sufficient evidence for a separate optimization-design package, not for an immediate schema mutation. `ACS_SEARCH_FOLD(column)` prevents existing ordinary text indexes from directly serving folded predicates. Also, player/event/opening/source substring semantics use leading wildcards, so simply adding folded B-tree columns would not automatically make those predicates index-searchable. The next package must benchmark semantics-preserving alternatives before migration: materialized folded columns for UDF-cost removal/prefix paths, and carefully bounded substring-search strategies only if they preserve literal `%`/`_`/backslash behavior, keyset paging, provenance, resource bounds and the single canonical application model.

Audit trail is explicit: initial run `32589731207` / job `97071530281` had focused 179/179 PASS and failed only because the new probe was invoked by file path and could not import repo-root `acs`. Module invocation fixed that infrastructure issue; no Product code/test assertion was weakened.

Ownership preserved: DEV1 UI/WebView; DEV2 canonical GameTree/domain/remote-session; DEV4 PGN/ChessBase/import security; DEV5 selective integration/promotion. Mistake/blunder scoring remains blocked on authoritative student/actor identity plus fixed evaluation perspective.

FRESH_WINDOWS_CANDIDATE=NO
NVDA_VERIFIED=NO
