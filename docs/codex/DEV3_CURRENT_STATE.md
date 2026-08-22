# AUTO-CHESS DEV3 current state

Lane: Full Product engine/analysis + ACSDB / Library / Search / import-export safety + presentation-neutral Books/Training progress backend contracts.

Active branch: `auto/dev3-acsdb-stable-paging-20260821`
Draft Product PR: #65 against `codex/full-product-20260821`
Evidence-only PR: #77, DO NOT MERGE.

Latest verified executable Product head: `1ca5784b3ce00837b40888a26dd1e94d8ce754ed`.
Exact GREEN CI run/job: `32558628088` / `96996629973`.
Workflow PR merge ref: `ff2fd2600e38b885a74f60fa1f61cf4956da1995`; its only delta above Product head is a documentation-only evidence marker.
Runner: GitHub runner 2.336.0; Ubuntu 24.04.4 image 20260816.277.1; Python 3.12.14.

New P1 delivered in this continuation: durable Training progress compare-and-swap persistence.
- `ExerciseSession` remains the canonical Training snapshot/restore semantic authority.
- New `TrainingProgressStore` only owns durable filesystem publication and optimistic concurrency; it does not parse moves, validate board state, or create another application/chess core.
- Create uses `expected_revision=None` and fails if progress already exists; updates require the exact SHA-256 revision returned by the previous load/save.
- A stale reader cannot silently overwrite a newer writer.
- Concurrent writers are serialized by an atomic peer lock directory and busy writes fail explicitly.
- Publication uses a peer temporary file, flush + fsync and atomic replacement. Synthetic publication failure leaves the prior durable file intact and removes temp/lock artifacts.
- Store envelope version/type/field validation fails closed; `ExerciseSession.restore()` rejects changed exercise definitions and malformed snapshots.
- Five deterministic regressions cover round-trip update, stale writer/create-only protection, definition/corruption rejection, strict revision/busy lock behavior and publication-failure recovery.
- Dedicated and Full Product DEV3 workflows now gate this module. The Full Product pull-request routing also accepts the exact active DEV3 branch as a validation base.

Exact CI evidence on `1ca5784b...` through merge ref `ff2fd260...`:
- diff hygiene PASS;
- compileall including `run_accessible_chess.py` PASS;
- focused DEV3 data/Books/Training suite: 78/78 PASS;
- full unittest discovery: 612/612 PASS;
- full pytest: 690 passed + 585 subtests passed;
- complete diagnostic: SELFTEST PASS and ACCESSIBLE CHESS 0.4 WEBVIEW2 COMPLETE USER FLOW DIAGNOSTIC PASS;
- all five new persistence tests PASS;
- no tests weakened or skipped for GREEN.

Previously verified DEV3 packages remain intact: ACSDB stable keyset paging/provenance/schema-v3/WAL/strict scalars/backup-recovery/query-plan, PGN and ACSDB atomic no-overwrite publication, Training schema-v2 revision-bound snapshots, BookReader semantic-target progress, index-fallback revision integrity, ambiguous durable-target write integrity and live-document mutation guards.

SAFE OVERLAP ownership remains:
- DEV2 owns canonical GameTree/domain work.
- DEV1 owns presentation/UI and Teacher presentation surfaces.
- DEV4 owns independent QA/security findings.
- DEV5 owns cross-lane integration/promotion.

Readiness:
- DEV3 ACSDB/Library/Search/recovery/query-plan package: `READY_FOR_INTEGRATION=YES`.
- Training revision-bound snapshot + durable CAS progress slices: COMPLETE / GREEN.
- Books durable reading-progress integrity slices: COMPLETE / GREEN.
- Overall DEV3 Full Product mission: PARTIAL.
- Next action: fresh ownership check, then another unclaimed dependency-correct ACSDB/Library/Search or presentation-neutral Books/Training/progress backend P1; stay SAFE OVERLAP on touching owned work.
- Non-blocking P2 hygiene: GitHub warns that actions target deprecated Node20 while the runner forces Node24.
- Frozen Stage1 release refs untouched. No Windows candidate created. Linux semantic accessibility tests do not constitute personal NVDA verification. `NVDA_VERIFIED=NO`.
