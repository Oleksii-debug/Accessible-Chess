# AUTO-CHESS DEV3 current state

Lane: Full Product engine/analysis + ACSDB / Library / Search + presentation-neutral Books/Training/Teacher/Student backend contracts.

Active Product branch: `auto/dev3-search-resource-bounds-20260822`
Draft Product PR: #92 against `auto/dev3-student-progress-store-20260822`
Verified executable Product head: `6f90516a8beefa8c191a8c593aaf3f2e410aa738`
Verified PR merge/evidence ref: `4bab8883cd293a0aa25d2a39d92e3a1abd4f6ff1`
Base DEV3 coordination head: `cad3921dff0a7dadafed253a90575d07b0b9c994`

Latest terminal-GREEN P1 package:
- bounds all presentation-neutral ACSDB Library/Search user text filters (`player`, `event`, `eco`, `opening`, `source_name`) to 256 normalized characters;
- rejects pathological oversized terms before SQLite execution;
- preserves literal LIKE escaping, strict no-coercion scalar validation, stable keyset paging, provenance, and the single canonical chess/application core;
- adversarial tests cover every text field, exact 256-character acceptance, whitespace normalization before the bound, rejection before database work, and non-text fail-closed behavior.

Exact current Product evidence:
- workflow `DEV3 Full Product ACSDB CI`
- run `32574651690`, job `97035089135` — SUCCESS
- checkout/evidence ref `4bab8883cd293a0aa25d2a39d92e3a1abd4f6ff1`
- diff hygiene PASS; compile PASS
- focused DEV3 data/engine-assisted/progress/search suite `130/130 PASS`
- full unittest `660/660 PASS`
- full pytest `738 passed + 628 subtests passed`
- SELFTEST PASS
- `ACCESSIBLE CHESS 0.4 WEBVIEW2 COMPLETE USER FLOW DIAGNOSTIC PASS`
- no skip/xfail/test weakening used to obtain GREEN.

CI history note: prior run `32574603178` / job `97034972349` failed only because one newly-authored DEV3 fixture expected an over-256 normalized term to pass. Commit `6f90516a...` corrected only that fixture to test normalization-before-bound semantics; Product behavior was not loosened.

Previously delivered terminal-GREEN DEV3 work remains intact, including durable StudentProgress CAS persistence from PR #90 and all prior ACSDB/Search/recovery/Training/Books/engine-assisted contracts.

Ownership / SAFE OVERLAP:
- DEV2 owns canonical GameTree/domain/core.
- DEV1 owns UI/WebView/Teacher presentation.
- DEV4 owns ChessBase/package/shared PGN-import security.
- DEV5 owns cross-lane integration/promotion.
- Frozen Stage1 refs remain untouched.

Decision: executable Product head `6f90516a...` is `READY_FOR_INTEGRATION=YES` for this isolated DEV3 package. Overall Full Product DEV3 mission remains `PARTIAL`.

Fresh Windows candidate: NONE from DEV3.
`NVDA_VERIFIED=NO`.
