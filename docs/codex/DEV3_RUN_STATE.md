# DEV3 RUN STATE

RUN_ID: 20260822-2102-unicode-search-performance-evidence
STATUS: COMPLETE / TERMINAL
READY_FOR_INTEGRATION: NO — evidence-only package; no Product behavior/schema delta
OVERALL_FULL_PRODUCT_DEV3: PARTIAL

BRANCH: auto/dev3-unicode-search-performance-evidence-20260822
EVIDENCE_PR: #107 (open/draft; evidence only, do not merge as Product history)
VALIDATION_PR: #108 (open/draft; validation only, do not merge)
INHERITED_PRODUCT_PACKAGE: PR #105, validated Product head 9c8a342e7dd98fee52c9776c0cb6a9b970d49296 remains READY_FOR_INTEGRATION=YES
PROBE_COMMIT: 19cc573f7588f13d6d988726c52d210b70e6e7eb
EVIDENCE_WORKFLOW_COMMIT: 6a105ff88b61673e8543fa7f67030cf1c5485191
CANONICAL_INVOCATION_FIX: f49897f77b5e0f62bafd0bec2b9c1ff6de85aa16
VALIDATION_HEAD: 06bb37a119f31d92dea93f537bc580facf5eebb2
VALIDATION_MERGE_REF: 770811ccaaeb694ca95dacf9b558b9efb0a06edf

PACKAGE: reproducible large-ACSDB Unicode Library/Search query-plan/performance evidence.
- seeds 100,000 games in an in-memory schema-v3 ACSDB;
- exercises the public GameSearchService rather than private SQL shortcuts;
- captures the exact executed SELECT through SQLite tracing and then EXPLAIN QUERY PLAN;
- repeats each query five times and reports median/min/max latency without asserting a wall-clock Product threshold;
- asserts semantic result counts and absence of temp-sort materialization;
- changes no database schema/index, search semantics, canonical chess/application state, UI, GameTree, PGN/import security, integration or release behavior.

EXACT GREEN CI EVIDENCE:
Workflow: DEV3 Full Product ACSDB CI
Run: 32589798970
Job: 97071708911
Conclusion: SUCCESS
Validated validation head: 06bb37a119f31d92dea93f537bc580facf5eebb2
Validation merge ref: 770811ccaaeb694ca95dacf9b558b9efb0a06edf
Focused DEV3 suite: 179/179 PASS
100k Unicode query-plan probe: PASS
Official Stockfish 18 bounded game-review smoke: PASS
Stockfish archive SHA-256: 536c0c2c0cf06450df0bfb5e876ef0d3119950703a8f143627f990c7b5417964 VERIFIED
Full unittest: 695/695 PASS
Full pytest: 773 passed + 641 subtests PASS
SELFTEST: PASS
ACCESSIBLE CHESS 0.4 WEBVIEW2 COMPLETE USER FLOW DIAGNOSTIC: PASS
Diff hygiene: PASS
Compile: PASS
TEST_WEAKENING: NONE

QUERY-PLAN/PERFORMANCE EVIDENCE ON UBUNTU-24.04 GITHUB RUNNER, CPYTHON 3.12.14, 100,000 ROWS:
- unicode_player_no_hit: PLAN=SCAN g + source PK lookup; median 145.941 ms, min 145.562, max 146.204.
- unicode_event_no_hit: PLAN=SCAN g + source PK lookup; median 68.261 ms, min 68.147, max 68.767.
- unicode_eco_prefix_no_hit: PLAN=SCAN g + source PK lookup; median 50.060 ms, min 49.908, max 50.480.
- unicode_player_common_hit(limit=50): PLAN=SCAN g + source PK lookup; median 1.190 ms, min 1.181, max 1.208 because LIMIT terminates early.
- unicode_player_keyset_tail_no_hit(after_game_id=90000): PLAN=SEARCH g USING INTEGER PRIMARY KEY (rowid>?) + source PK lookup; median 16.432 ms, min 16.284, max 16.477.
- no case used a temporary B-tree for ORDER BY.

INTERPRETATION: the measurement proves full-row scans for first-page folded no-hit player/event/ECO queries. Existing ordinary text indexes cannot serve ACS_SEARCH_FOLD(column) predicates. This is material enough to justify a separate design/benchmark package, but it does not justify guessing a schema change. Substring filters with leading wildcards require special care: materialized folded columns may remove Python-UDF CPU cost but do not automatically make substring predicates B-tree searchable. Next work must compare semantics-preserving alternatives before migration.

AUDIT TRAIL: initial validation run 32589731207 / job 97071530281 had focused 179/179 PASS and failed only because the probe was invoked as `python tools/...py`, which did not put repo root on import path. Invocation was corrected to `python -m tools.dev3_unicode_search_perf_probe`; no Product code or assertions were weakened.

OWNERSHIP: DEV1 UI/WebView; DEV2 canonical GameTree/domain/remote-session; DEV4 PGN/ChessBase/import security; DEV5 integration/promotion. DEV3 did not mutate those lanes.
KNOWN_BLOCKER: mistake/blunder classification still awaits terminal authoritative student/actor plus fixed evaluation-perspective contract.
FRESH_WINDOWS_CANDIDATE: NO
NVDA_VERIFIED: NO
