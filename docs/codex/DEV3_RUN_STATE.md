# AUTO-CHESS DEV3 run state

STATUS: COMPLETE FOR BOOKREADER INDEX-FALLBACK REVISION-INTEGRITY P1 / FULL PRODUCT MISSION PARTIAL
BRANCH: `auto/dev3-acsdb-stable-paging-20260821`
PR: #65
DIRECTIVE: Full Product DEV3 / engine-analysis + ACSDB-Library-Search-import-export safety + presentation-neutral Books/Training progress backend contracts

Latest verified executable Product head: `99b5c61c31585d7b2474a050eeb006bf639943dd`.
Exact GREEN CI run: `32550533728`.
Exact CI job: `96976421604`.
PR merge ref executed: `c134100d797d5436ec3f7ff4a6aa4d7a84f3cdf9` against Full Product base `656e8ec311e364e6e54a30504fd30a4aaff586f9`.

Product defect closed:
- BookReader durable progress used stable `block:*` / `source:*` semantic targets when identifiers existed, but persisted `index:N` when a block had neither identifier;
- an index fallback could previously survive a document insertion or semantic edit and silently restore onto whichever block later occupied that number;
- snapshot schema is now v2 with strict `fallback_digests` for referenced `index:*` targets only;
- digest identity is SHA-256 over canonical JSON of the presentation-neutral semantic block payload;
- stable block/source identities preserve their existing reorder-safe behavior without digest coupling;
- index-only exact-revision round trips remain valid, while insertion or semantic edits at the same index fail closed;
- missing/extra, malformed and coercive fallback digest data fails closed;
- schema v1 requires explicit persistence-adapter migration rather than implicit compatibility;
- no second chess rules, legality, GameTree, board or presentation authority was introduced.

Executable evidence on `99b5c61c...` through merge ref `c134100d...`:
- diff hygiene PASS;
- compileall PASS;
- focused DEV3 data/reading-progress suite 65/65 PASS;
- full unittest 599/599 PASS;
- full pytest 677 passed + 581 subtests PASS;
- all 12 dedicated BookReader progress-contract regressions PASS;
- no tests weakened/skipped for GREEN.

SAFE OVERLAP:
- DEV2 canonical GameTree/domain untouched;
- DEV1 presentation/UI/Teacher surfaces untouched;
- DEV4 QA/security ownership untouched;
- DEV5 integration target/promotion ownership untouched.

READY_FOR_INTEGRATION: YES for the isolated existing DEV3 ACSDB/Library/Search/recovery/query-plan package, Training revision-bound persistence slice, and Books durable reading-progress/index-fallback integrity slice.
OVERALL_FULL_PRODUCT_DEV3: PARTIAL.
NEXT_ACTION: fresh ownership check, then another unclaimed dependency-correct ACSDB/Library/Search or presentation-neutral Books/Training/progress backend P1.
NVDA_VERIFIED: NO
WINDOWS_CANDIDATE: NONE created by DEV3.
BLOCKER: none for this isolated slice; integration/release authority remains DEV5/Auditor.
