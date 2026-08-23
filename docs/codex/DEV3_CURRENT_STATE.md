# DEV3 CURRENT STATE

DEV3 remains in SAFE OVERLAP release-support mode under the Stage1 release freeze. The accepted-then-RELEASE_HOLD Stage1 base used by the current release repair is `manual5/integration-20260821 @ 80720e8125c59a213f278668d599040f2768d553`.

DEV3 QA PR #159 independently proved a release-critical `StockfishRuntime.resolve_stockfish_path()` diagnostic privacy gap on exact `80720e8...`: run `32634729467` failed the 3-case privacy oracle on Ubuntu and Windows while the pre-existing Stockfish runtime regressions remained 18/18 PASS. This proves path disclosure, not a Stockfish/runtime correctness defect.

DEV5 PR #167 is now the active Product owner. Current exact head is `a06c81e424c599f996662e8898c2b1cbf8ee9dbd`, with base SHA `80720e8125c59a213f278668d599040f2768d553`. Exact workflow `DEV5 Stage1 Stockfish Runtime Path Privacy Repair`, run `32635555544`, is fully GREEN:
- Windows exact QA oracle `97184638496` SUCCESS;
- Ubuntu exact QA oracle `97184638731` SUCCESS;
- Ubuntu full regression `97184638645` SUCCESS;
- Windows full regression `97184638744` SUCCESS.
Both full-regression jobs pass exact source/diff hygiene, compile, current Stage1 privacy + Stockfish surface, focused Stage1 release contracts, full unittest, full pytest and complete diagnostic. The Windows job preserves LF source bytes before frozen-byte identity tests.

Earlier PR #167 REDs from head `f68794b...` are superseded: one was a stale inherited allowlist rejecting the newly added Stockfish repair files; the other was Windows CRLF materialization at frozen-byte tests. Current exact `a06c81e4...` resolves those evidence-environment issues without weakening Product assertions.

DEV3 validation PR #168 is not current-head approval evidence. It was rooted on superseded DEV4 repair variant `d34bc6f5354620ebf327fb88f3165c085c435361`, and the branch now has a parallel DEV3 writer. DEV3 therefore stopped all further pushes there and left only a classification comment. Current PR #167 exact CI is the stronger release evidence.

QA release PR #160 is tied to privacy-defective `80720e8...`; its observed V4 run failed before Product materialization/build, and no candidate artifact from that chain can be accepted. No fresh Windows archive is certified.

The terminal DEV3 Full Product slice remains PR #137 (`AnalysisService` provider-result resource bounds), technically GREEN for later selective intake and separate from Stage1 release authority.

SAFE_OVERLAP=YES
PROVEN_STAGE1_STOCKFISH_RUNTIME_PATH_PRIVACY_DEFECT=YES
PR167_CURRENT_HEAD=a06c81e424c599f996662e8898c2b1cbf8ee9dbd
PR167_CURRENT_EXACT_CI=GREEN
PR167_AUDIT_PROMOTION=PENDING
DEV3_PRODUCT_PATCH_REQUIRED=NO
FRESH_WINDOWS_CANDIDATE=NO
NVDA_VERIFIED=NO
