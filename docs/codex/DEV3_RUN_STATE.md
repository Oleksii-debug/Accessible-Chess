# DEV3 RUN STATE

RUN_ID: 20260823-0020-analysis-provider-bounds
STATUS: COMPLETE / TERMINAL / TECHNICAL_GREEN
READY_FOR_INTEGRATION: YES
OVERALL_FULL_PRODUCT_DEV3: PARTIAL

BRANCH: auto/dev3-analysis-provider-bounds-20260823
DRAFT_PR: #137
PARENT_COORDINATION_HEAD: 02241201b0fff72abdacd9157053d12f5c665d05
PRODUCT_CODE_COMMIT: 2e6e9e7767960c602d06a139948def6f9c400765
VALIDATED_PRODUCT_TEST_HEAD: 7bcab25b54649663ba9f3094adbd14d49fdc3ced
PRE_TERMINAL_REPORTING_HEAD: 022cc8168a209ffe7bdfa16779cdd0aed382ca00
CI_BASE_HEAD: f5eea253770383b8212dfc1eb4af5815266cceca

PACKAGE: presentation-neutral AnalysisService provider-result resource bounds.
- provider outer Sequence is size-checked against requested MultiPV before tuple materialization;
- legacy PV Sequence is size-checked before tuple materialization;
- AnalysisLine caps PVs at the established 256-ply safety ceiling;
- AnalysisResult caps result lines at the established 10-line MultiPV ceiling;
- exact limits remain valid;
- adversarial ExplosiveSequence regressions prove rejection without item iteration.

EXACT MACHINE EVIDENCE:
Workflow: DEV3 Analysis Provider Bounds CI
Run: 32599676493
Job: 97095971890
Conclusion: SUCCESS
Focused analysis/provider/cross-service regressions: 79/79 PASS
Full unittest: 723/723 PASS
Full pytest: 801 passed + 651 subtests PASS
Diff hygiene: PASS
Compile: PASS
SELFTEST: PASS
ACCESSIBLE CHESS 0.4 WEBVIEW2 COMPLETE USER FLOW DIAGNOSTIC: PASS
TEST_WEAKENING: NONE

CONCURRENCY CUT-OFF: a parallel DEV3 package PR #134 terminalized during this run and independently closed the final-review history-node-id bound. It does not overlap this AnalysisService package. Do not duplicate it.

AUDIT RELEASE-FREEZE CUT-OFF: latest canonical Audit handoff is ACTIVE / STAGE1 RELEASE FREEZE / FRESH WINDOWS CANDIDATE PRIORITY. This run was already active and is now terminal. Do not start another Full Product expansion wave before a fresh Stage1 candidate decision. Accepted Stage1 authority is manual5/integration-20260821 @ 0fa442330bc2bb03636ff9297512da4c29e38684.

NEXT: DEV3 release-support verification only on exact accepted Stage1 source: Stockfish runtime, analysis, clocks, lifecycle and packaged Stockfish behavior. Evidence-only unless a concrete candidate-facing release blocker is proven and ownership explicitly permits repair. Do not modify QA-owned strict Windows harness.

FRESH_WINDOWS_CANDIDATE: NO
NVDA_VERIFIED: NO
