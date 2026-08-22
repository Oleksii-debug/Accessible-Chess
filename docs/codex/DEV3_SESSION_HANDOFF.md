# AUTO-CHESS DEV3 session handoff

UTC checkpoint: 2026-08-22T05:05Z executable verification completed.

Continued the same DEV3 Full Product work on `auto/dev3-acsdb-stable-paging-20260821` / draft PR #65. Live ownership remained SAFE OVERLAP constrained: DEV2 owns canonical GameTree/domain, DEV1 presentation/UI and Teacher surfaces, DEV4 independent QA/security, and DEV5 integration/promotion. This run selected an unclaimed presentation-neutral Books/progress integrity P1.

The generic `docs/codex/CURRENT_STATE.md`, `docs/codex/NEXT_WORK.md`, `docs/codex/SESSION_HANDOFF.md`, and root `AGENTS.md` were not present on the live DEV3 branch; DEV3-prefixed coordination files are the available lane truth.

Latest verified executable Product head: `86a2e6de3e1d89b939d31b6b5aa6de8100505c23`.
Exact verification run/job: `32553387781` / `96983670899` — SUCCESS.
Workflow PR merge ref: `89cd9cb4ee7b140bb1924e58f9b10aed3b7a5ad2` against Full Product base `656e8ec311e364e6e54a30504fd30a4aaff586f9`.
Runner: GitHub runner 2.336.0, Ubuntu 24.04.4 image 20260816.277.1, Python 3.12.14.

Delivered:
- audited the BookReader durable write boundary after the existing semantic-target and index-fallback integrity work;
- found that duplicate `block_id` or `source_anchor` identities were correctly rejected by `BookIndex.resolve()` during restore, but `save_return_point()` / `snapshot()` could first serialize the same ambiguous target successfully;
- added a unique-resolution preflight before mutating return-point state or publishing durable snapshots;
- ensured a failed return-point save is atomic and cannot poison a later valid snapshot;
- snapshot publication now validates every referenced durable target before emitting state;
- added `tests/test_dev3_bookreader_ambiguous_persistence.py` with four deterministic regressions for duplicate block IDs, duplicate source anchors, atomic failed save, and the unchanged unique-target round trip;
- added the new regression module to the focused DEV3 CI gate.

No canonical chess legality, GameTree, board, UI, keybinding or NVDA presentation authority was introduced or modified. No test was weakened or skipped.

Terminal executable evidence on `86a2e6de...` through merge ref `89cd9cb4...`:
- diff hygiene PASS;
- compileall PASS;
- focused DEV3 data/reading-progress suite 69/69 PASS;
- full unittest 603/603 PASS;
- full pytest 681 passed + 581 subtests PASS;
- all 4 ambiguous-persistence regressions PASS.

Decision:
- BookReader ambiguous durable-target write-integrity P1 is COMPLETE and exact executable-head GREEN;
- existing DEV3 ACSDB/Library/Search/recovery/query-plan package remains `READY_FOR_INTEGRATION=YES`;
- Training revision-bound and prior Books revision-integrity slices remain COMPLETE / GREEN;
- overall DEV3 Full Product mission remains PARTIAL;
- next action after fresh live ownership check: another unclaimed dependency-correct ACSDB/Library/Search or presentation-neutral Books/Training/progress backend P1; remain SAFE OVERLAP if touching work is owned;
- frozen Stage1 release refs untouched;
- fresh Windows candidate: NONE;
- `NVDA_VERIFIED=NO`;
- DEV5/Auditor retain integration/release authority.
