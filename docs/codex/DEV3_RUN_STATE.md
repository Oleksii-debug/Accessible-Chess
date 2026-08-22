# AUTO-CHESS DEV3 run state

STATUS: COMPLETE FOR DURABLE TRAINING PROGRESS CAS P1 / FULL PRODUCT MISSION PARTIAL
BRANCH: `auto/dev3-acsdb-stable-paging-20260821`
PR: #65
DIRECTIVE: Full Product DEV3 / engine-analysis + ACSDB-Library-Search-import-export safety + presentation-neutral Books/Training progress backend contracts

Latest verified executable Product head: `1ca5784b3ce00837b40888a26dd1e94d8ce754ed`.
Exact GREEN CI run: `32558628088`.
Exact CI job: `96996629973`.
Validation PR: #77, evidence-only / DO NOT MERGE.
Workflow PR merge ref executed: `ff2fd2600e38b885a74f60fa1f61cf4956da1995` = exact Product head plus one documentation-only evidence marker.
Runner: GitHub runner 2.336.0; Ubuntu 24.04.4 image 20260816.277.1; Python 3.12.14.

P1 delivered:
- added presentation-neutral `TrainingProgressStore` for durable `ExerciseSession` state;
- exact Training schema-v2 semantics remain owned by `ExerciseSession.snapshot()` / `ExerciseSession.restore()`;
- first publication is create-only; callers must pass the exact previously observed SHA-256 revision to update existing progress;
- stale or unobserved writers fail closed instead of last-writer-wins;
- a peer lock directory serializes writers and fails closed when another writer owns publication;
- writes use a peer temporary file, flush + fsync, then atomic `os.replace`; publication failure preserves prior durable state and cleans temp/lock artifacts;
- corrupt/future envelopes, invalid expected revisions and changed exercise definitions fail explicitly;
- no second chess rules, legality, GameTree, board, UI, keybinding or presentation authority was introduced.

Executable evidence on `1ca5784b...` through merge ref `ff2fd260...`:
- diff hygiene PASS;
- compileall including launcher PASS;
- focused DEV3 data/Books/Training suite 78/78 PASS;
- all 5 new durable Training progress regressions PASS;
- full unittest 612/612 PASS;
- full pytest 690 passed + 585 subtests PASS;
- `python run_accessible_chess.py --diagnostic`: SELFTEST PASS and complete WebView2 user-flow diagnostic PASS;
- no tests weakened/skipped for GREEN.

SAFE OVERLAP:
- DEV2 canonical GameTree/domain untouched;
- DEV1 presentation/UI/Teacher surfaces untouched;
- DEV4 QA/security ownership untouched;
- DEV5 integration target/promotion ownership untouched.

READY_FOR_INTEGRATION: YES for the isolated existing DEV3 ACSDB/Library/Search/recovery/query-plan package, Training revision-bound snapshot + durable CAS persistence slices, and Books durable reading-progress integrity slices.
OVERALL_FULL_PRODUCT_DEV3: PARTIAL.
NEXT_ACTION: fresh ownership check, then another unclaimed dependency-correct ACSDB/Library/Search or presentation-neutral Books/Training/progress backend P1. P2 only when no higher-value P1 remains: Actions currently emit a non-blocking Node20-target deprecation warning while GitHub forces Node24.
NVDA_VERIFIED: NO
WINDOWS_CANDIDATE: NONE created by DEV3.
BLOCKER: none for this isolated slice; integration/release authority remains DEV5/Auditor.
