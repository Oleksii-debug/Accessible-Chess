# AUTO-CHESS DEV3 current state

Lane: Full Product engine/analysis + ACSDB / Library / Search / import-export safety + presentation-neutral Books/Training progress backend contracts.

Active Product branch: `auto/dev3-acsdb-stable-paging-20260821`
Draft Product PR: #65 against `codex/full-product-20260821`
Current validation-only PR: #81 against the exact DEV3 Product branch; DO NOT MERGE.

Current executable Product checkpoint before handoff-only documentation commits: `753ba0ac27e37a944820b2917f2fd2518be283e5`.
Implementation/test commits in this slice:
- `0bf8dc2041421914948350fe48b0e3a03e9d65bd` — escape literal SQLite LIKE metacharacters in ACSDB search;
- `a3c93e319cc7c01126dd3a6dd8a3e945b9bf4032` — deterministic literal `%`, `_`, `\\` regressions;
- `753ba0ac27e37a944820b2917f2fd2518be283e5` — add `tests.test_search_service` to the focused Full Product DEV3 CI gate.

New P1 in this continuation: deterministic literal text semantics for ACSDB / Library / Search.
- Search values were already parameterized against SQL injection, but SQLite `LIKE` still interpreted user-entered `%` and `_` as wildcard operators.
- `GameSearchService` now escapes `\\`, `%` and `_` and uses an explicit SQLite `ESCAPE '\\'` clause for player, event, ECO, opening and source-name filters.
- Existing substring/prefix behavior and `COLLATE NOCASE` remain unchanged for normal text.
- ECO retains prefix search semantics, but any metacharacter supplied by the user is literal text rather than a wildcard.
- Regressions cover literal percent, underscore, backslash, source-name combinations and ECO prefix text.
- No chess legality, canonical GameTree, board, UI, keybinding, Windows or NVDA presentation authority was introduced or modified.

Verification state for the new slice:
- independent SQLite semantic smoke for `%`, `_`, `\\`: PASS;
- repository-local clone/test execution from this runtime: BLOCKED because the container cannot resolve `github.com`;
- validation PR #81 merge ref initially observed as `1cf56c3ef57d5b9bddc3bb9e3e89347f5b649957` before handoff-only Product documentation commits;
- GitHub workflow result for the new exact Product checkpoint: PENDING / not yet returned by the connector at this checkpoint;
- therefore the new literal-search slice is NOT YET CLAIMED GREEN or READY_FOR_INTEGRATION.

Previous verified executable Product head remains `1ca5784b3ce00837b40888a26dd1e94d8ce754ed`, exact GREEN run/job `32558628088` / `96996629973`, merge ref `ff2fd2600e38b885a74f60fa1f61cf4956da1995`.
Previously verified DEV3 packages remain intact: ACSDB stable keyset paging/provenance/schema-v3/WAL/strict scalars/backup-recovery/query-plan, PGN and ACSDB atomic no-overwrite publication, Training schema-v2 revision-bound snapshots + durable CAS persistence, and BookReader durable semantic progress integrity.

SAFE OVERLAP ownership remains:
- DEV2 owns canonical GameTree/domain work.
- DEV1 owns presentation/UI and Teacher presentation surfaces.
- DEV4 owns independent QA/security findings.
- DEV5 owns cross-lane integration/promotion.

Next action: on the next checkpoint, re-read PR #65/#81 and exact branch head, collect applicable GitHub Actions for the final documentation-synchronized composition, inspect any failing log without weakening tests, and only then mark this literal-search P1 GREEN. If GREEN, close PR #81 unmerged and continue to another unclaimed dependency-correct ACSDB/Library/Search or presentation-neutral Books/Training/progress backend P1.

Frozen Stage1 release refs untouched. No Windows candidate created. Linux/search tests are not personal NVDA evidence. `NVDA_VERIFIED=NO`.
