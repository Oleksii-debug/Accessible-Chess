# DEV3 NEXT WORK

Start every next DEV3 wave with a fresh live ownership read and preserve terminal packages unless a concrete defect is proven.

Latest completed DEV3 wave: `auto/dev3-unicode-search-performance-evidence-20260822`. It is evidence-only and COMPLETE/TERMINAL, not an integration candidate. The inherited Unicode Library/Search Product package remains PR #105, validated Product head `9c8a342e7dd98fee52c9776c0cb6a9b970d49296`, READY_FOR_INTEGRATION=YES.

Measured 100k evidence from CI run `32589798970` / job `97071708911` proves that first-page Unicode-folded no-hit player/event/ECO queries use full `SCAN g`; observed medians on that runner were 145.941 ms / 68.261 ms / 50.060 ms. Keyset tail after id 90,000 narrowed the scan via the integer primary key and measured 16.432 ms. These are environment-specific evidence values, not Product latency thresholds.

Highest READY DEV3 priorities now:
1. design and benchmark a semantics-preserving ACSDB Unicode-search optimization against the measured baseline before any migration. Compare at least materialized folded shadow columns (to remove repeated Python UDF folding and improve eligible prefix paths) with a bounded substring-search strategy for player/event/opening/source-name filters. Do not assume an ordinary B-tree fixes leading-wildcard substring matching. Preserve NFKC+casefold correctness, literal `%`/`_`/backslash semantics, 256-character resource bounds, keyset paging, source provenance, strict scalar validation and the one canonical data/application model. Require migration/reopen/backward-compatibility evidence before shipping schema changes;
2. Books/Training persistence/progress recovery and concurrency gaps that remain unclaimed;
3. engine-assisted Teacher visibility/analysis policy and engine cancellation/recovery/concurrency where backend-only and not owned by DEV1/DEV2;
4. mistake/blunder analytics only after authoritative StudentGame/Assignment actor identity and fixed evaluation-perspective contract are terminal.

Do not edit DEV2 canonical GameTree/domain/remote-session semantics, DEV4 PGN/ChessBase/import security, DEV1 UI/WebView models, DEV5 integration/promotion, or frozen Stage1 release lineage. Never create a second canonical chess/application state model. Use official Stockfish where engine behavior is under test and never turn shared-runner wall-clock values into hard Product assertions without an explicit stable performance contract.

For each package: focused adversarial tests, broad unittest/pytest, diff/compile, applicable diagnostic, exact observable CI, recoverable commits, canonical Drive 12 handoff update/read-back when available, and repo RUN_STATE/current/next/session synchronization.

FRESH_WINDOWS_CANDIDATE=NO
NVDA_VERIFIED=NO
