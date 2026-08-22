# AUTO-CHESS DEV3 current state

Lane: Full Product engine/analysis + ACSDB / Library / Search / import-export safety + presentation-neutral Books/Training progress backend contracts.

Active Product branch: `auto/dev3-acsdb-stable-paging-20260821`
Draft Product PR: #65 against `codex/full-product-20260821`
Validation-only PR for this continuation: #84; DO NOT MERGE.

Current executable Product head: `3dde3a7444c9cf594e92e32f5e084c8969015ad4`.
Implementation commit: `fada1ed8fd31762cb8054ac67124c3a72bd39a28`.
Regression-test commit: `3dde3a7444c9cf594e92e32f5e084c8969015ad4`.

Current P1: fail-closed SQLite INTEGER boundaries for presentation-neutral Library/Search query scalars.
- `source_id` and `after_game_id` now reject integers above signed 64-bit SQLite INTEGER range before a database bind can raise a raw `OverflowError`.
- Existing strict type rules remain: booleans/non-ints are rejected; `source_id` remains positive-only; `after_game_id` remains non-negative.
- Exact SQLite maximum `(2**63)-1` remains valid and yields an ordinary empty page when no matching row exists.
- Added deterministic regressions for both overflow paths and the valid upper boundary.
- No chess rules, canonical GameTree, board, UI, keybinding, Windows candidate or integration target changed.

Validation state for this new P1:
- local clone/test execution: BLOCKED in this runtime because container DNS cannot resolve `github.com`;
- exact-base validation-only branch: `auto/dev3-search-scalar-ci-evidence-20260822`;
- validation-only PR #84 base is the executable Product head and head adds documentation-only marker `2220325a1d69cf46bf4611b36f0337378e8ab527`;
- applicable GitHub Actions run has not yet appeared through the connector at this checkpoint;
- therefore this new P1 is `IMPLEMENTED / CI_PENDING`, not yet claimed GREEN or READY_FOR_INTEGRATION.

Last terminally verified executable Product head remains `85b88d2efd8fb92f0be5500e5a8da2b86228e46a`, GREEN run/job `32561369567` / `97003308118`, merge ref `d075bc872f40af64a3470fd5d4e869574a8a866a`; focused 85/85, full unittest 614/614, full pytest 692 passed + 585 subtests, compile/diff/diagnostic PASS.

SAFE OVERLAP ownership preserved: DEV2 canonical GameTree/domain; DEV1 presentation/UI/Teacher; DEV4 independent QA/security; DEV5 integration/promotion. Frozen Stage1 refs untouched.

Next action: obtain terminal exact-base CI for #84, inspect any RED without weakening tests, then close #84 unmerged if GREEN and synchronize all DEV3 handoff files/PR #65 to the exact verified executable head. `NVDA_VERIFIED=NO`.
