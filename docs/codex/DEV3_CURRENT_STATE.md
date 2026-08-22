# DEV3 CURRENT STATE

Current DEV3 wave is an evidence-only Unicode ACSDB search optimization benchmark, not a Product migration.

Branch: `auto/dev3-unicode-search-shadow-benchmark-20260822`.
Evidence PR: #109, open/draft/evidence-only.
Validation PR: #110, open/draft/validation-only.
Executable benchmark head: `e930a53c3617da9f9676bc44a55a565bff630875`.
Validation base: `0da0187f07e11e489d353e866ab679b3320e3a87`.
Validation marker head: `5f98ee96214641e65417fee14e2f0d4010a1df34`.

The benchmark seeds 100,000 games into a disposable in-memory ACSDB and compares public `GameSearchService` result IDs against a candidate query shape using materialized NFKC+casefold shadow columns for white, black, event, ECO, opening and source name. It creates candidate indexes only inside that disposable database, captures `EXPLAIN QUERY PLAN`, reports whether a temporary ORDER BY B-tree appears, and measures baseline/candidate timings without any wall-clock acceptance threshold.

Semantic equivalence remains strict: player/event/ECO/opening/source-name cases, common hits, no-hits, literal `%`, `_`, backslash escaping and keyset-tail behavior must return exactly the same visible game IDs as the public service. Candidate plan characteristics are recorded as evidence rather than converted into correctness assertions.

No Product schema/version, migration, search-service behavior, canonical chess/application state, UI/WebView, GameTree/domain, PGN/ChessBase/import security, integration or release lineage is changed by this wave. The inherited shippable Unicode correctness package remains PR #105 at validated Product head `9c8a342e7dd98fee52c9776c0cb6a9b970d49296`, `READY_FOR_INTEGRATION=YES`.

CI is not yet observable through the connected GitHub evidence API for validation head `5f98ee96214641e65417fee14e2f0d4010a1df34`; therefore this wave is `IN_PROGRESS / CI_EVIDENCE_PENDING`, not GREEN. Local execution was also unavailable because the execution container could not resolve github.com, so no local PASS is claimed.

Previous 100k baseline evidence remains terminal GREEN: run `32589798970`, job `97071708911`; player/event/ECO first-page no-hit queries used full scans with medians 145.941 ms / 68.261 ms / 50.060 ms on that runner. Those values are environment-specific evidence, not Product thresholds.

Ownership preserved: DEV1 UI/WebView; DEV2 canonical GameTree/domain/remote-session; DEV4 PGN/ChessBase/import security; DEV5 selective integration/promotion. Mistake/blunder scoring remains blocked on authoritative student/actor identity plus fixed evaluation perspective.

FRESH_WINDOWS_CANDIDATE=NO
NVDA_VERIFIED=NO
