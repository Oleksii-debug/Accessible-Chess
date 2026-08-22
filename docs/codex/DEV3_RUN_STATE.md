# DEV3 RUN STATE

RUN_ID: 20260822-2204-unicode-search-shadow-benchmark
STATUS: IN_PROGRESS / CI_EVIDENCE_PENDING
READY_FOR_INTEGRATION: NO — evidence-only benchmark; no Product behavior/schema delta
OVERALL_FULL_PRODUCT_DEV3: PARTIAL

BRANCH: auto/dev3-unicode-search-shadow-benchmark-20260822
EVIDENCE_PR: #109 (open/draft; evidence only, do not merge as Product history)
VALIDATION_PR: #110 (open/draft; validation only, do not merge)
BASE_EVIDENCE_HEAD: 4f10a19891e957544cf4dcb3df1be85977340097 (PR #107 terminal evidence)
EXECUTABLE_BENCHMARK_HEAD: e930a53c3617da9f9676bc44a55a565bff630875
VALIDATION_BASE_HEAD: 0da0187f07e11e489d353e866ab679b3320e3a87
VALIDATION_MARKER_HEAD: 5f98ee96214641e65417fee14e2f0d4010a1df34
INHERITED_PRODUCT_PACKAGE: PR #105, validated Product head 9c8a342e7dd98fee52c9776c0cb6a9b970d49296 remains READY_FOR_INTEGRATION=YES

PACKAGE: semantics-preserving design benchmark for materialized Unicode-folded ACSDB search shadow columns.
- seeds 100,000 games in a disposable in-memory schema-v3 ACSDB;
- compares exact result IDs from public GameSearchService against a candidate shadow-column query shape;
- candidate materializes NFKC+casefold values once for white/black/event/ECO/opening/source name and creates temporary benchmark indexes only inside the disposable database;
- covers player/event/ECO/opening/source-name no-hits, common player hits, literal percent/underscore/backslash escaping and keyset-tail semantics;
- reports EXPLAIN QUERY PLAN, temp-sort presence and five repeated baseline/candidate timings without asserting a wall-clock threshold;
- exact result-id equivalence is mandatory; candidate temp-sort behavior is evidence, not a correctness assertion;
- changes no Product schema, migration, search service, canonical chess/application state, UI, GameTree, PGN/import security, integration or release behavior.

CI STATUS: dedicated pull-request validation surface is prepared, but no GitHub Actions run is yet observable through the connected GitHub evidence API for validation head 5f98ee96214641e65417fee14e2f0d4010a1df34. Therefore CI is INCONCLUSIVE/PENDING, not GREEN.
LOCAL EXECUTION: unavailable because the execution container has no DNS access to github.com; no local PASS is claimed.

NEXT ACTION: continue this same package when exact Actions evidence becomes observable. If GREEN, capture benchmark timings/plans and decide whether shadow columns justify a separate schema-v4 Product migration. If RED, fix benchmark/CI defects without weakening semantic equivalence tests. Do not ship a schema migration from this evidence package itself.

OWNERSHIP: DEV1 UI/WebView; DEV2 canonical GameTree/domain/remote-session; DEV4 PGN/ChessBase/import security; DEV5 integration/promotion. DEV3 did not mutate those lanes.
KNOWN_BLOCKER: mistake/blunder classification still awaits terminal authoritative student/actor identity plus fixed evaluation-perspective contract.
FRESH_WINDOWS_CANDIDATE: NO
NVDA_VERIFIED: NO
