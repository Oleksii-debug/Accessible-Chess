# DEV3 SESSION HANDOFF

Current package is still in progress because exact GitHub Actions evidence is not yet observable. Do not start a new Product package; continue this same shadow-column benchmark wave first.

Evidence branch: `auto/dev3-unicode-search-shadow-benchmark-20260822`
Evidence PR: #109 (draft/evidence-only)
Executable benchmark head: `e930a53c3617da9f9676bc44a55a565bff630875`
Validation PR: #110 (draft/validation-only)
Validation base: `0da0187f07e11e489d353e866ab679b3320e3a87`
Validation marker head: `5f98ee96214641e65417fee14e2f0d4010a1df34`
Inherited Product package: PR #105 / validated head `9c8a342e7dd98fee52c9776c0cb6a9b970d49296` remains `READY_FOR_INTEGRATION=YES`.

What was done:
- added `tools/dev3_unicode_search_shadow_benchmark.py`;
- benchmark seeds 100,000 games in a disposable in-memory ACSDB;
- candidate materializes NFKC+casefold shadow values for white/black/event/ECO/opening/source name and benchmark-only indexes;
- exact visible game IDs are compared against public `GameSearchService` for no-hit/common-hit, ECO prefix, source-name, literal `%`/`_`/backslash and keyset-tail cases;
- candidate `EXPLAIN QUERY PLAN`, temp-sort flag and five repeated baseline/candidate timings are reported without a latency threshold;
- added dedicated `DEV3 Unicode Search Shadow Benchmark CI` with focused Unicode/search tests, prior 100k baseline probe, candidate benchmark, full unittest, full pytest and complete diagnostic;
- candidate temp-sort behavior is intentionally evidence-only; semantic result-id divergence remains a hard failure.

What was not done:
- no ACSDB schema-version bump or migration;
- no Product `GameSearchService` change;
- no UI/WebView, GameTree/domain, PGN/ChessBase/import-security, integration, packaging, Windows or NVDA mutation;
- no performance claim from local execution because the execution container could not resolve github.com.

CI truth at handoff: no Actions workflow run is observable yet through the connected GitHub commit/workflow/status surfaces for validation head `5f98ee96214641e65417fee14e2f0d4010a1df34`. Therefore status is `CI_EVIDENCE_PENDING / INCONCLUSIVE`, not GREEN.

Next exact action: re-read PR #110 and exact workflow evidence. If GREEN, record the benchmark plans/timings and determine whether shadow columns justify a separate schema-v4 migration package. If RED, repair benchmark/CI defects without weakening exact semantic equivalence. Preserve the previous terminal baseline evidence and PR #105 Product candidate.

READY_FOR_INTEGRATION=NO for this evidence-only wave.
OVERALL_FULL_PRODUCT_DEV3=PARTIAL
FRESH_WINDOWS_CANDIDATE=NO
NVDA_VERIFIED=NO
