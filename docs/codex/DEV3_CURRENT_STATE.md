# AUTO-CHESS DEV3 current state

Lane: Full Product data core / ACSDB / Library / Search

Active branch: `auto/dev3-acsdb-stable-paging-20260821`
Code checkpoint SHA: `8c017a141246b58141fa5b6eca30b6b7830bd86f`
Draft PR: #65 against `codex/full-product-20260821`

Implemented in this checkpoint:
- deterministic keyset paging for `AcsDatabase.search_games()` via `after_id`;
- deterministic newest-first keyset paging for `list_import_attempts()` via `before_id`;
- cursor/limit validation that rejects booleans and negative cursors;
- `search_position()` now shares bounded-limit validation;
- regression tests for paging stability while new imports are inserted;
- regression tests proving filters remain active across pages.

The change is isolated from frozen Stage1 release lineage and does not claim Windows/NVDA evidence. `NVDA_VERIFIED=NO`.

Verification state at this handoff:
- GitHub accepted both code/test commits and PR #65 is mergeable.
- No pull-request workflow run was attached to exact code SHA when checked.
- No claim of local/full-suite GREEN is made because this automation environment had connector access but no network-capable repository checkout.
