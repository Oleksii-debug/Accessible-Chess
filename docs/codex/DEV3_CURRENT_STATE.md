# AUTO-CHESS DEV3 current state

Lane: Full Product engine/analysis + ACSDB / Library / Search + presentation-neutral Books/Training/Teacher/Student backend contracts.

Active Product branch: `auto/dev3-bookreader-snapshot-bounds-20260822`
Draft Product PR: #95
Current executable Product/test/CI head: `85fd447dbc2864fd7e507703aa0c4d342526854f`
Prior terminal coordination base: `eb0279c151156bf3b3f3a0ffc43ef2ec38d0d200`

Current P1 package:
- bounds BookReader durable return points at 1,000;
- rejects oversized return-point maps before iterating restore entries;
- bounds return-point names at 256 characters before mutation;
- bounds durable semantic target keys at 4,096 characters before BookIndex resolution;
- bounds fallback-digest map cardinality before iteration;
- preserves strict schema-v2, exact semantic target identity, fallback-digest checks and the live BookDocument revision guard;
- adds adversarial tests including exact-limit acceptance;
- does not duplicate canonical chess/GameTree state, UI state or engine state.

Validation truth:
- new focused tests are wired into `DEV3 Full Product ACSDB CI`.
- exact-head Actions outcome for `85fd447d...` is not currently observable through the available connector lookup, so this package is NOT claimed GREEN.
- `READY_FOR_INTEGRATION=NO` until exact CI is observed.
- prior StudentProgress resource-bound package at `4c0f5885e51aa93ad366dccaf61a962c930f5ef0` remains terminal GREEN and independently ready for DEV5 intake.

Ownership / SAFE OVERLAP:
- DEV2 owns canonical GameTree/domain/core.
- DEV1 owns UI/WebView/Teacher presentation.
- DEV4 owns ChessBase/package/shared PGN-import security.
- DEV5 owns cross-lane integration/promotion.
- frozen Stage1 refs remain untouched.

Overall Full Product DEV3 mission remains `PARTIAL`.
Fresh Windows candidate: NONE from DEV3.
`NVDA_VERIFIED=NO`.
