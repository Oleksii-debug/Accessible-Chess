# AUTO-CHESS DEV3 run state

STATUS: IN_PROGRESS / SEARCH-SCALAR P1 IMPLEMENTED / CI_PENDING
BRANCH: `auto/dev3-acsdb-stable-paging-20260821`
PRODUCT PR: #65
VALIDATION PR: #84 — EVIDENCE ONLY / DO NOT MERGE
DIRECTIVE: Full Product DEV3 / engine-analysis + ACSDB-Library-Search-import-export safety + presentation-neutral Books/Training progress backend contracts

Current executable Product head: `3dde3a7444c9cf594e92e32f5e084c8969015ad4`.
Implementation: `fada1ed8fd31762cb8054ac67124c3a72bd39a28`.
Regression tests: `3dde3a7444c9cf594e92e32f5e084c8969015ad4`.

P1 implemented:
- `source_id` and `after_game_id` fail closed before SQLite bind when above signed 64-bit INTEGER max;
- exact upper bound remains valid;
- strict non-bool integer and existing positivity/non-negativity contracts preserved;
- deterministic overflow and upper-bound regressions added;
- no GameTree/chess-rules/UI/keybinding/integration target changes.

CURRENT VALIDATION:
- local clone/tests blocked by runtime DNS resolution failure for github.com;
- validation branch `auto/dev3-search-scalar-ci-evidence-20260822`;
- PR #84 head `2220325a1d69cf46bf4611b36f0337378e8ab527` contains documentation-only CI marker over exact executable Product base;
- applicable Actions run not yet visible through connector;
- DO NOT CLAIM GREEN until terminal exact-base workflow evidence exists.

LAST TERMINAL GREEN: executable head `85b88d2efd8fb92f0be5500e5a8da2b86228e46a`; run/job `32561369567` / `97003308118`; merge ref `d075bc872f40af64a3470fd5d4e869574a8a866a`; focused 85/85; unittest 614/614; pytest 692 + 585 subtests; compile/diff/diagnostic PASS.

SAFE OVERLAP: DEV2 canonical GameTree/domain untouched; DEV1 presentation/UI/Teacher untouched; DEV4 QA/security untouched; DEV5 integration/promotion untouched.
NEXT_ACTION: poll #84 exact-base CI; if RED inspect logs and repair without weakening tests; if GREEN close #84 unmerged, update PR #65 and all DEV3 coordination files to exact evidence.
READY_FOR_INTEGRATION: previous verified DEV3 package YES; new search-scalar P1 NO while CI_PENDING.
NVDA_VERIFIED: NO
WINDOWS_CANDIDATE: NONE created by DEV3.
