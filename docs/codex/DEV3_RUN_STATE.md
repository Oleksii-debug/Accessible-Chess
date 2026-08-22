# AUTO-CHESS DEV3 run state

STATUS: COMPLETE FOR BOOKREADER LIVE-MUTATION DURABLE-PROGRESS P1 / FULL PRODUCT MISSION PARTIAL
BRANCH: `auto/dev3-acsdb-stable-paging-20260821`
PR: #65
DIRECTIVE: Full Product DEV3 / engine-analysis + ACSDB-Library-Search-import-export safety + presentation-neutral Books/Training progress backend contracts

Latest verified executable Product head: `feaa097bb9c87667132fcede7c0d192503b1d7b9`.
Exact GREEN CI run: `32556145719`.
Exact CI job: `96990471833`.
PR merge ref executed: `4147f3cee7277db773f1cac16a87fd1b7cf63950` against Full Product base `656e8ec311e364e6e54a30504fd30a4aaff586f9`.
Runner: GitHub runner 2.336.0; Ubuntu 24.04.4 image 20260816.277.1; Python 3.12.14.

Product defect closed:
- `BookReader` owns an immutable `BookIndex` snapshot while `BookDocument.blocks` and block identities are mutable;
- in-place reorder/insert/identity edits could leave durable save/restore/snapshot operations resolving through stale index metadata;
- `BookReader` now fingerprints the semantic block revision at construction and fails closed before any durable target operation if that indexed revision changed;
- progress saved before authoring edits remains restorable into a fresh reader when stable semantic IDs still identify the same content;
- no second chess rules, legality, GameTree, board, UI, keybinding or presentation authority was introduced.

Executable evidence on `feaa097b...` through merge ref `4147f3c...`:
- diff hygiene PASS;
- compileall including launcher PASS;
- focused DEV3 data/reading-progress suite 73/73 PASS;
- full unittest 607/607 PASS;
- full pytest 685 passed + 581 subtests PASS;
- all 4 dedicated live-mutation regressions PASS;
- `python run_accessible_chess.py --diagnostic`: SELFTEST PASS and complete WebView2 user-flow diagnostic PASS;
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
