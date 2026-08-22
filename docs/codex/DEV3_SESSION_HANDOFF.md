# DEV3 SESSION HANDOFF

DEV3 completed the evidence-first P1 follow-up for ACSDB Unicode Library/Search performance. This wave is intentionally evidence-only: no Product schema/index/search behavior was changed. The inherited Unicode correctness Product package remains PR #105 / validated Product head `9c8a342e7dd98fee52c9776c0cb6a9b970d49296`, READY_FOR_INTEGRATION=YES.

Evidence branch: `auto/dev3-unicode-search-performance-evidence-20260822`
Evidence PR: #107, open/draft; do not merge as Product history
Validation PR: #108, validation-only; do not merge
Probe commit: `19cc573f7588f13d6d988726c52d210b70e6e7eb`
Evidence workflow commit: `6a105ff88b61673e8543fa7f67030cf1c5485191`
Canonical invocation fix: `f49897f77b5e0f62bafd0bec2b9c1ff6de85aa16`
Exact GREEN validation head: `06bb37a119f31d92dea93f537bc580facf5eebb2`
Validation merge ref: `770811ccaaeb694ca95dacf9b558b9efb0a06edf`

Evidence delivered: reproducible `tools/dev3_unicode_search_perf_probe.py` seeds 100,000 games, calls the public `GameSearchService`, captures exact SELECT text through SQLite tracing, runs `EXPLAIN QUERY PLAN`, executes five repeated samples, and reports median/min/max without hard-coding a shared-runner latency threshold. It asserts expected page sizes and that no temporary ORDER BY B-tree is introduced.

Exact CI: `DEV3 Full Product ACSDB CI` run `32589798970`, job `97071708911`, SUCCESS. Focused 179/179 PASS; 100k probe PASS; official Stockfish 18 smoke PASS with verified SHA-256 `536c0c2c0cf06450df0bfb5e876ef0d3119950703a8f143627f990c7b5417964`; full unittest 695/695 PASS; pytest 773 passed + 641 subtests PASS; SELFTEST and complete WebView2 diagnostic PASS; diff hygiene/compile PASS; no test weakening.

Measured on Ubuntu 24.04 / CPython 3.12.14 Actions runner, 100,000 rows: player no-hit median 145.941 ms, event no-hit 68.261 ms, ECO-prefix no-hit 50.060 ms; all three planned as `SCAN g` plus source primary-key lookup. Common player hit with limit 50 also planned `SCAN g` but stopped early at median 1.190 ms. Player keyset-tail no-hit after id 90,000 used `SEARCH g USING INTEGER PRIMARY KEY (rowid>?)`, median 16.432 ms. No case used a temp sort.

Interpretation: the folded UDF on stored columns prevents ordinary text indexes from directly serving these predicates, and the measured full scans justify an optimization-design package. Do not jump straight to a B-tree migration: leading-wildcard substring semantics for player/event/opening/source name remain inherently different from ECO prefix matching. Next DEV3 work should benchmark semantics-preserving shadow-fold/prefix and bounded substring strategies, including migration/reopen compatibility, before changing schema.

Audit trail retained: first validation run `32589731207` / job `97071530281` passed focused 179/179 then failed only because the new probe was invoked by file path and could not import repo-root `acs`. Invocation was changed to module mode; no Product code/test assertion was weakened.

Ownership preserved: DEV1 UI/WebView; DEV2 canonical GameTree/domain/remote-session; DEV4 PGN/ChessBase/import security; DEV5 selective integration/promotion. Mistake/blunder scoring remains dependency-blocked on authoritative actor identity plus fixed evaluation perspective.

READY_FOR_INTEGRATION=NO (evidence-only wave; inherited PR #105 remains YES)
OVERALL_FULL_PRODUCT_DEV3=PARTIAL
FRESH_WINDOWS_CANDIDATE=NO
NVDA_VERIFIED=NO
