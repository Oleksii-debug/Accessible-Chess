# AUTO-CHESS DEV3 session handoff

Delivered a second coherent Full Product P1 increment on `auto/dev3-acsdb-stable-paging-20260821`, extending the earlier ACSDB stable-paging package without touching frozen Stage1 lineage.

Product/test checkpoint: `b6e5b0a6f801083462581c49c834793490dba465`.
Verification-workflow checkpoint: `820d3d54294e19d9f3fbbd28937f45cc0b27c10b`.
Draft PR: #65, base `codex/full-product-20260821`.

Product/test delta for this continuation:
- `acs/acsdb.py`
- `tests/test_dev3_acsdb_position_provenance.py`

Verification support delta:
- `.github/workflows/dev3-full-product-data-ci.yml`

Behavior added:
- `search_position(..., after_game_id=..., after_ply=...)` composite keyset cursor over the unique `(game_id, ply)` ordering;
- stable exact-position paging when matching rows/imports are inserted between pages;
- provenance fields on game-search and exact-position rows: `source_name`, `source_format`, `source_sha256`, `source_imported_at`;
- strict composite-cursor validation;
- backward-compatible positional `search_position(fen, limit)` behavior retained after second-pass review.

Regression coverage added:
- provenance on game-search rows;
- provenance on exact-position rows;
- exact-position paging stability with a late row behind the cursor and a later imported game ahead of it;
- incomplete, boolean and negative composite cursors;
- positional limit compatibility exercised directly.

CI/test evidence:
- added `DEV3 Full Product Data CI` on branch pushes;
- workflow compiles ACSDB/GameTree/import-contract/tests, runs focused `tests.test_acsdb` + `tests.test_dev3_acsdb_position_provenance`, then full `unittest discover`;
- outbound git clone still fails in this runtime due DNS resolution, so local executable tests were not available;
- the available GitHub connector enumerates only pull-request-associated workflow runs for a commit and did not provide an observable result for this push-only workflow before handoff;
- therefore this handoff does NOT claim executable GREEN.

Current decision:
- `READY_FOR_INTEGRATION=NO` pending observable terminal focused/full test evidence;
- `NVDA_VERIFIED=NO`;
- do not merge into frozen Stage1 refs;
- next DEV3 wave should inspect PR #65/head first and consume exact CI evidence before any further Product expansion.
