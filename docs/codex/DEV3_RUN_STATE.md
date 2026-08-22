# AUTO-CHESS DEV3 run state

STATUS: COMPLETE FOR BOOKREADER AMBIGUOUS-DURABLE-TARGET P1 / FULL PRODUCT MISSION PARTIAL
BRANCH: `auto/dev3-acsdb-stable-paging-20260821`
PR: #65
DIRECTIVE: Full Product DEV3 / engine-analysis + ACSDB-Library-Search-import-export safety + presentation-neutral Books/Training progress backend contracts

Latest verified executable Product head: `86a2e6de3e1d89b939d31b6b5aa6de8100505c23`.
Exact GREEN CI run: `32553387781`.
Exact CI job: `96983670899`.
PR merge ref executed: `89cd9cb4ee7b140bb1924e58f9b10aed3b7a5ad2` against Full Product base `656e8ec311e364e6e54a30504fd30a4aaff586f9`.
Runner: GitHub runner 2.336.0; Ubuntu 24.04.4 image 20260816.277.1; Python 3.12.14.

Product defect closed:
- `BookIndex.resolve()` already rejected duplicate `block:*` / `source:*` semantic identities, but `BookReader.save_return_point()` and `BookReader.snapshot()` could serialize those ambiguous keys before restore later rejected them;
- durable progress could therefore be successfully written in a state that was not restorable against the same document snapshot;
- the write boundary now resolves every durable target before mutating a return point or publishing a snapshot;
- failed return-point persistence is atomic and does not poison later snapshots;
- duplicate block IDs and duplicate source anchors both fail closed before durable progress publication;
- unique semantic targets and existing schema-v2 index-fallback digest behavior remain unchanged;
- no second chess rules, legality, GameTree, board, UI, keybinding or presentation authority was introduced.

Executable evidence on `86a2e6de...` through merge ref `89cd9cb4...`:
- diff hygiene PASS;
- compileall PASS;
- focused DEV3 data/reading-progress suite 69/69 PASS;
- full unittest 603/603 PASS;
- full pytest 681 passed + 581 subtests PASS;
- all 4 dedicated ambiguous-persistence regressions PASS;
- no tests weakened/skipped for GREEN.

SAFE OVERLAP:
- DEV2 canonical GameTree/domain untouched;
- DEV1 presentation/UI/Teacher surfaces untouched;
- DEV4 QA/security ownership untouched;
- DEV5 integration target/promotion ownership untouched.

READY_FOR_INTEGRATION: YES for the isolated existing DEV3 ACSDB/Library/Search/recovery/query-plan package, Training revision-bound persistence slice, and Books durable reading-progress integrity slices.
OVERALL_FULL_PRODUCT_DEV3: PARTIAL.
NEXT_ACTION: fresh ownership check, then another unclaimed dependency-correct ACSDB/Library/Search or presentation-neutral Books/Training/progress backend P1.
NVDA_VERIFIED: NO
WINDOWS_CANDIDATE: NONE created by DEV3.
BLOCKER: none for this isolated slice; integration/release authority remains DEV5/Auditor.
