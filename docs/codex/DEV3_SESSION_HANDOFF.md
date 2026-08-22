# AUTO-CHESS DEV3 session handoff

UTC checkpoint: 2026-08-22T03:04Z executable verification completed.

Continued the same DEV3 Full Product work on `auto/dev3-acsdb-stable-paging-20260821` / draft PR #65. Live ownership remained SAFE OVERLAP constrained: DEV2 owns canonical GameTree/domain, DEV1 presentation/UI and Teacher surfaces, DEV4 independent QA/security, and DEV5 integration/promotion. This run selected an unclaimed presentation-neutral Training/progress integrity P1.

Latest verified executable Product head: `c85a489cde459831990d67a717c8e6bf47ad9dd2`.
Exact verification run/job: `32547927505` / `96969673770` — SUCCESS.
Workflow PR merge ref: `ae65bcdf838ccd1e438f7db1acbad161cdfd25b1` against Full Product base `656e8ec311e364e6e54a30504fd30a4aaff586f9`.
Runner: GitHub runner 2.336.0, Ubuntu 24.04.4 image 20260816.277.1, Python 3.12.14.

Delivered:
- audited Training progress restore and found snapshots were tied only to stable `exercise_id` plus numeric counters/index;
- identified silent semantic drift when an exercise retained its ID but changed `start_fen`, accepted solution moves, or solution-step order;
- upgraded the strict snapshot exchange to schema v2 with a SHA-256 `definition_digest`;
- definition digest covers only presentation-neutral semantic identity: normalized `start_fen` and the ordered accepted-move sets for all steps;
- changed/reordered solutions and changed start positions now fail explicitly as a different exercise revision even when `exercise_id` is unchanged;
- presentation-only edits to title, tags, source metadata, hints or explanations remain compatible with existing progress;
- malformed digest shapes/types fail closed; no scalar coercion is accepted;
- schema v1 is explicitly unsupported at restore because it cannot prove revision identity; migration responsibility remains at the persistence-adapter boundary;
- expanded `tests/test_dev3_training_snapshot_contract.py` to 12 deterministic regressions covering exact v2 payload, old/future schema rejection, digest validation, semantic-revision rejection, presentation-only compatibility and exact roundtrip.

No canonical chess legality, GameTree, board, UI, keybinding or NVDA presentation authority was introduced or modified. No test was weakened or skipped.

Terminal executable evidence on `c85a489c...` through merge ref `ae65bcdf...`:
- diff hygiene PASS;
- compileall PASS;
- focused DEV3 data/reading-progress suite 61/61 PASS;
- full unittest 595/595 PASS;
- full pytest 673 passed + 574 subtests PASS;
- all 12 Training revision-integrity contract regressions PASS.

Decision:
- Training revision-integrity P1 is COMPLETE and exact executable-head GREEN;
- existing DEV3 ACSDB/Library/Search/recovery/query-plan package remains `READY_FOR_INTEGRATION=YES`;
- Books durable reading-progress slice remains COMPLETE / GREEN;
- overall DEV3 Full Product mission remains PARTIAL;
- next action after fresh live ownership check: another unclaimed dependency-correct ACSDB/Library/Search or presentation-neutral Books/Training/progress backend P1; remain SAFE OVERLAP if touching work is owned;
- frozen Stage1 release refs untouched;
- fresh Windows candidate: NONE;
- `NVDA_VERIFIED=NO`;
- DEV5/Auditor retain integration/release authority.
