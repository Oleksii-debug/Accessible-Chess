# AUTO-CHESS DEV3 run state

STATUS: COMPLETE FOR TRAINING REVISION-INTEGRITY P1 / FULL PRODUCT MISSION PARTIAL
BRANCH: `auto/dev3-acsdb-stable-paging-20260821`
PR: #65
DIRECTIVE: Full Product DEV3 / engine-analysis + ACSDB-Library-Search-import-export safety + presentation-neutral Books/Training progress backend contracts

Latest verified executable Product head: `c85a489cde459831990d67a717c8e6bf47ad9dd2`.
Exact GREEN CI run: `32547927505`.
Exact CI job: `96969673770`.
PR merge ref executed: `ae65bcdf838ccd1e438f7db1acbad161cdfd25b1` against Full Product base `656e8ec311e364e6e54a30504fd30a4aaff586f9`.

Product defect closed:
- Training snapshots previously identified only `exercise_id`, so progress could silently survive a same-ID edit that changed `start_fen` or the ordered accepted solution and then resume against different exercise semantics;
- snapshot schema is now v2 with strict `definition_digest` revision identity;
- digest authority is limited to presentation-neutral exercise semantics: normalized `start_fen` and ordered accepted-move sets;
- changed start positions, changed solution moves and reordered steps fail closed even under the same exercise ID;
- title/tags/source metadata/hints/explanations do not invalidate compatible progress;
- malformed/coercive digest values fail closed;
- schema v1 has no revision identity and therefore requires explicit persistence-adapter migration rather than implicit compatibility;
- no second chess rules, legality, GameTree, board or presentation authority was introduced.

Executable evidence on `c85a489c...` through merge ref `ae65bcdf...`:
- diff hygiene PASS;
- compileall PASS;
- focused DEV3 data/reading-progress suite 61/61 PASS;
- full unittest 595/595 PASS;
- full pytest 673 passed + 574 subtests PASS;
- all 12 dedicated Training revision-integrity regressions PASS;
- no tests weakened/skipped for GREEN.

SAFE OVERLAP:
- DEV2 canonical GameTree/domain untouched;
- DEV1 presentation/UI/Teacher surfaces untouched;
- DEV4 QA/security ownership untouched;
- DEV5 integration target/promotion ownership untouched.

READY_FOR_INTEGRATION: YES for the isolated existing DEV3 ACSDB/Library/Search/recovery/query-plan package, Training revision-bound persistence slice, and Books durable reading-progress slice.
OVERALL_FULL_PRODUCT_DEV3: PARTIAL.
NEXT_ACTION: fresh ownership check, then another unclaimed dependency-correct ACSDB/Library/Search or presentation-neutral Books/Training/progress backend P1.
NVDA_VERIFIED: NO
WINDOWS_CANDIDATE: NONE created by DEV3.
BLOCKER: none for this isolated slice; integration/release authority remains DEV5/Auditor.
