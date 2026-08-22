# AUTO-CHESS DEV3 session handoff

UTC checkpoint: 2026-08-22T02:02Z executable verification completed.

Continued the same DEV3 Full Product work on `auto/dev3-acsdb-stable-paging-20260821` / draft PR #65. Live ownership remained SAFE OVERLAP constrained: DEV2 owns canonical GameTree/domain, DEV1 presentation/UI and Teacher surfaces, DEV4 independent QA/security, and DEV5 integration/promotion. This run therefore selected an unclaimed presentation-neutral Books/progress backend P1.

Latest verified executable Product head: `7e0d933b1fa6b48318d09683757bb1a54f44ef75`.
Exact verification run/job: `32545080795` / `96962002799` — SUCCESS.
Workflow PR merge ref: `6a1538bcac605f33cc22888ea0045a2324506faa` against Full Product base `656e8ec311e364e6e54a30504fd30a4aaff586f9`.
Runner: GitHub runner 2.336.0, Ubuntu 24.04.4 image 20260816.277.1, Python 3.12.14.

Delivered:
- audited `BookReader` progress and found return points persisted only as raw block indices;
- identified silent semantic drift: after inserting/reordering source-preserving content, an old numeric offset could point at another block without any error;
- reused existing `BookIndex` as the single semantic target authority (`block_id`, then `source_anchor`, then snapshot-local index fallback);
- changed named return points to stable target keys and added semantic target restoration;
- added exact `BOOK_READER_SNAPSHOT_SCHEMA_VERSION = 1` snapshot exchange for current reading target plus named return targets;
- made snapshot restore reject missing/unknown fields, unsupported versions and coercive scalar/container forms;
- made deleted targets fail explicitly and duplicate/ambiguous identities fail closed through `BookIndex.resolve`;
- added `tests/test_dev3_bookreader_progress_contract.py` with 8 deterministic regressions covering exact payload, source-preserving reorder, missing/ambiguous targets, schema/type rejection, empty-book roundtrip and scalar coercion.

No canonical chess legality, GameTree, board, UI, keybinding or NVDA presentation authority was introduced or modified. No test was weakened or skipped.

Terminal executable evidence on `7e0d933...`:
- diff hygiene PASS;
- compileall PASS;
- focused DEV3 data/reading-progress suite 56/56 PASS;
- full unittest 590/590 PASS;
- full pytest 668 passed + 567 subtests PASS;
- all 8 BookReader progress contract regressions PASS.

Decision:
- Books durable reading-progress P1 is COMPLETE and exact executable-head GREEN;
- existing DEV3 ACSDB/Library/Search/recovery/query-plan package remains `READY_FOR_INTEGRATION=YES`;
- Training strict snapshot-contract slice remains COMPLETE / GREEN;
- overall DEV3 Full Product mission remains PARTIAL;
- next action after fresh live ownership check: another unclaimed dependency-correct ACSDB/Library/Search or presentation-neutral Books/Training/progress backend P1; remain SAFE OVERLAP if touching work is owned;
- frozen Stage1 release refs untouched;
- fresh Windows candidate: NONE;
- `NVDA_VERIFIED=NO`;
- DEV5/Auditor retain integration/release authority.
