# AUTO-CHESS DEV3 session handoff

UTC checkpoint: 2026-08-22T07:05Z executable verification completed.

Continued the same DEV3 Full Product work on `auto/dev3-acsdb-stable-paging-20260821` / draft PR #65. Live ownership remained SAFE OVERLAP constrained: DEV2 owns canonical GameTree/domain, DEV1 presentation/UI and Teacher surfaces, DEV4 independent QA/security, and DEV5 integration/promotion. This run selected an unclaimed presentation-neutral Training/progress durability P1.

GitHub branch/SHA/tests/CI remained technical truth. Generic root coordination paths were not treated as newer than the active DEV3-prefixed lane files. No frozen Stage1 ref, DEV2/DEV1/DEV4/DEV5 owned Product area, Windows candidate or NVDA claim was touched.

Latest verified executable Product head: `1ca5784b3ce00837b40888a26dd1e94d8ce754ed`.
Exact verification run/job: `32558628088` / `96996629973` — SUCCESS.
Validation PR: #77 — evidence-only / DO NOT MERGE.
Workflow PR merge ref: `ff2fd2600e38b885a74f60fa1f61cf4956da1995`; the only delta above Product head is a documentation-only validation marker.
Runner: GitHub runner 2.336.0, Ubuntu 24.04.4 image 20260816.277.1, Python 3.12.14.

Delivered:
- audited the existing strict schema-v2 `ExerciseSession` snapshot/restore contract and identified the missing durable publication/concurrency boundary;
- added `acs/training_progress_store.py` as infrastructure-only persistence around canonical Training snapshots;
- first save is create-only; updates require the exact previously observed SHA-256 revision;
- stale or unobserved writers fail closed rather than silently overwriting newer progress;
- an atomic peer lock directory serializes writers and busy writes fail explicitly;
- writes use a peer temporary file, flush + fsync and atomic `os.replace` publication;
- synthetic publication failure preserves the prior durable file and cleans temporary/lock artifacts;
- corrupt/future envelopes, malformed revisions and changed exercise definitions are rejected explicitly;
- added `tests/test_dev3_training_progress_store.py` with five deterministic regressions;
- added the new module/tests to dedicated and Full Product DEV3 CI gates;
- corrected DEV3 validation routing so pull requests against the exact active Product branch can produce observable CI evidence;
- superseded validation PR #76 was closed unmerged after its base filter was found not to trigger the intended workflow.

No canonical chess legality, GameTree, board, UI, keybinding or NVDA presentation authority was introduced or modified. No test was weakened or skipped.

Terminal executable evidence on `1ca5784b...` through merge ref `ff2fd260...`:
- diff hygiene PASS;
- compileall including launcher PASS;
- focused DEV3 data/Books/Training suite 78/78 PASS;
- all 5 new durable Training progress regressions PASS;
- full unittest 612/612 PASS;
- full pytest 690 passed + 585 subtests PASS;
- SELFTEST PASS;
- ACCESSIBLE CHESS 0.4 WEBVIEW2 COMPLETE USER FLOW DIAGNOSTIC PASS.

Decision:
- durable Training progress CAS P1 is COMPLETE and exact executable-head GREEN;
- existing DEV3 ACSDB/Library/Search/recovery/query-plan package remains `READY_FOR_INTEGRATION=YES`;
- Training revision-bound snapshot and Books durable reading-progress integrity slices remain COMPLETE / GREEN;
- overall DEV3 Full Product mission remains PARTIAL;
- next action after fresh live ownership check: another unclaimed dependency-correct ACSDB/Library/Search or presentation-neutral Books/Training/progress backend P1; remain SAFE OVERLAP if touching work is owned;
- Node20-target Actions deprecation warning while runner forces Node24 is non-blocking P2 hygiene only;
- fresh Windows candidate: NONE;
- Linux accessibility contract tests are not human NVDA evidence;
- `NVDA_VERIFIED=NO`;
- DEV5/Auditor retain integration/release authority.
