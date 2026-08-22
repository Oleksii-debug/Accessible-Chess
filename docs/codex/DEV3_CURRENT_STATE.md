# AUTO-CHESS DEV3 current state

Lane: Full Product engine/analysis + ACSDB / Library / Search / import-export safety + presentation-neutral Training/progress backend contracts.

Active branch: `auto/dev3-acsdb-stable-paging-20260821`
Draft PR: #65 against `codex/full-product-20260821`

Latest verified executable head: `d49482e90089c640869a697dce9fff9abd9f3519`.
Exact GREEN CI run/job: `32542435950` / `96954884846`.
Workflow merge ref: `0d3e69a2207a4fb471ca84663e61292d66ebbeeb` against Full Product base `656e8ec311e364e6e54a30504fd30a4aaff586f9`.
Runner: GitHub runner 2.336.0; Ubuntu 24.04 image 20260816.277.1; Python 3.12.14.

New P1 delivered in this continuation: strict versioned Training progress snapshot exchange.
- `ExerciseSession.snapshot()` now emits exact schema v1 with explicit `schema_version`.
- `restore()` rejects missing/unknown fields instead of silently defaulting them.
- schema version, exercise identity, counters and status use exact scalar types; booleans, floats and numeric strings are not coerced.
- unsupported future schema versions fail closed; persistence migrations must be explicit before restore.
- counter and completion-state invariants remain validated.
- no chess legality, GameTree, board, UI or presentation authority was added; training still treats canonical move/FEN semantics as external core-owned facts.
- dedicated regression file: `tests/test_dev3_training_snapshot_contract.py` (7 tests).

Exact CI evidence on `d49482e...`:
- diff hygiene PASS;
- compileall `acs tests` PASS;
- focused DEV3 ACSDB suite: 36/36 PASS;
- full unittest discovery: 582/582 PASS;
- full pytest: 660 passed + 560 subtests passed;
- all 7 new Training snapshot contract regressions PASS;
- no tests weakened or skipped for GREEN.

Previously verified DEV3 package remains intact: ACSDB stable keyset paging/provenance/schema-v3/WAL/strict scalars/backup-recovery/query-plan evidence plus PGN and ACSDB atomic no-overwrite publication closures.

SAFE OVERLAP ownership remains:
- DEV2 owns canonical GameTree/domain work.
- DEV1 owns presentation/UI and Teacher presentation surfaces.
- DEV4 owns its independent QA/security findings in PR #67.
- DEV5 owns cross-lane integration/promotion.

Readiness:
- DEV3 ACSDB/Library/Search/recovery/query-plan package: `READY_FOR_INTEGRATION=YES`.
- Training snapshot-contract P1: COMPLETE / exact executable head GREEN.
- Overall DEV3 Full Product mission: PARTIAL.
- Next action: fresh ownership check, then another unclaimed presentation-neutral Training/Books/Teacher/progress backend P1 or dependency-correct ACSDB/Library/Search boundary; stay SAFE OVERLAP on touching owned work.
- Frozen release refs untouched. No Windows candidate created. `NVDA_VERIFIED=NO`.
