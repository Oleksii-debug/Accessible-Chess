# AUTO-CHESS DEV3 run state

STATUS: COMPLETE FOR BOOKREADER DURABLE READING-PROGRESS P1 / FULL PRODUCT MISSION PARTIAL
BRANCH: `auto/dev3-acsdb-stable-paging-20260821`
PR: #65
DIRECTIVE: Full Product DEV3 / engine-analysis + ACSDB-Library-Search-import-export safety + presentation-neutral Books/Training progress backend contracts

Latest verified executable Product head: `7e0d933b1fa6b48318d09683757bb1a54f44ef75`.
Exact GREEN CI run: `32545080795`.
Exact CI job: `96962002799`.
PR merge ref executed: `6a1538bcac605f33cc22888ea0045a2324506faa` against Full Product base `656e8ec311e364e6e54a30504fd30a4aaff586f9`.

Product defect closed:
- BookReader return points were raw numeric block offsets, so a source-preserving structural edit could silently restore a reader to the wrong semantic block;
- progress now uses the existing BookIndex stable target model (`block_id`, then `source_anchor`, then explicit snapshot-local index fallback);
- snapshot exchange is exact schema v1 with current semantic target plus named return targets;
- missing/unknown fields, unsupported versions and coercive shapes fail closed;
- missing or ambiguous semantic targets fail explicitly instead of drifting or being guessed;
- no second chess rules, legality, GameTree, board or presentation authority was introduced.

Executable evidence on `7e0d933...`:
- diff hygiene PASS;
- compileall PASS;
- focused DEV3 data/reading-progress suite 56/56 PASS;
- full unittest 590/590 PASS;
- full pytest 668 passed + 567 subtests PASS;
- all 8 dedicated BookReader progress regressions PASS;
- no tests weakened/skipped for GREEN.

SAFE OVERLAP:
- DEV2 canonical GameTree/domain untouched;
- DEV1 presentation/UI/Teacher surfaces untouched;
- DEV4 QA/security ownership untouched;
- DEV5 integration target/promotion ownership untouched.

READY_FOR_INTEGRATION: YES for the isolated existing DEV3 ACSDB/Library/Search/recovery/query-plan package, Training persistence-contract slice, and Books durable reading-progress slice.
OVERALL_FULL_PRODUCT_DEV3: PARTIAL.
NEXT_ACTION: fresh ownership check, then another unclaimed dependency-correct ACSDB/Library/Search or presentation-neutral Books/Training/progress backend P1.
NVDA_VERIFIED: NO
WINDOWS_CANDIDATE: NONE created by DEV3.
BLOCKER: none for this isolated slice; integration/release authority remains DEV5/Auditor.
