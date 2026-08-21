# AUTO-CHESS DEV3 current state

Lane: Full Product data core / ACSDB / Library / Search

Active branch: `auto/dev3-acsdb-stable-paging-20260821`
Draft PR: #65 against `codex/full-product-20260821`

Latest Product/test checkpoint: `b6e5b0a6f801083462581c49c834793490dba465`
Latest verification-workflow checkpoint: `820d3d54294e19d9f3fbbd28937f45cc0b27c10b`

Current coherent package now includes:
- deterministic keyset paging for `AcsDatabase.search_games()` via `after_id`;
- deterministic newest-first keyset paging for `list_import_attempts()` via `before_id`;
- deterministic composite keyset paging for `search_position()` via `(after_game_id, after_ply)`;
- cursor/limit validation rejecting ambiguous boolean/negative cursor values;
- preservation of the legacy positional `search_position(fen, limit)` call contract;
- provenance-aware game and exact-position search rows with source name, format, SHA-256 and import timestamp;
- regression coverage for paging stability while new imports/position rows are inserted, filter preservation, provenance and cursor validation;
- a DEV3 Full Product data CI workflow that compiles the data core, runs focused ACSDB tests and full unittest discovery on branch pushes.

Verification state:
- GitHub accepted all Product/test/CI commits and PR #65 remains the evidence PR.
- The branch CI was configured and push-triggered, but the available connector can only enumerate pull-request-associated runs for a commit; it does not expose this push workflow run ID/result.
- No local repository checkout is available in this runtime because outbound git DNS resolution fails.
- Therefore no executable GREEN claim is made in this handoff.

`READY_FOR_INTEGRATION=NO` pending observable terminal focused/full test evidence.
`NVDA_VERIFIED=NO`.
