# AUTO-CHESS DEV3 session handoff

UTC checkpoint: 2026-08-22T04:02Z executable verification completed.

Continued the same DEV3 Full Product work on `auto/dev3-acsdb-stable-paging-20260821` / draft PR #65. Live ownership remained SAFE OVERLAP constrained: DEV2 owns canonical GameTree/domain, DEV1 presentation/UI and Teacher surfaces, DEV4 independent QA/security, and DEV5 integration/promotion. This run selected an unclaimed presentation-neutral Books/progress integrity P1.

The generic `docs/codex/CURRENT_STATE.md`, `docs/codex/NEXT_WORK.md`, `docs/codex/SESSION_HANDOFF.md`, and root `AGENTS.md` were not present on the live DEV3 branch; DEV3-prefixed coordination files are the available lane truth.

Latest verified executable Product head: `99b5c61c31585d7b2474a050eeb006bf639943dd`.
Exact verification run/job: `32550533728` / `96976421604` — SUCCESS.
Workflow PR merge ref: `c134100d797d5436ec3f7ff4a6aa4d7a84f3cdf9` against Full Product base `656e8ec311e364e6e54a30504fd30a4aaff586f9`.
Runner: GitHub runner 2.336.0, Ubuntu 24.04.4 image 20260816.277.1, Python 3.12.14.

Delivered:
- audited BookReader durable progress after the prior semantic-target work and found a residual mismatch between contract and persistence behavior: blocks lacking `block_id` and `source_anchor` used `index:N`, which BookIndex describes as snapshot-local but BookReader persisted durably;
- identified silent semantic drift when a source revision inserted content before an index-only target or changed the block at the same numeric index;
- upgraded BookReader snapshot exchange to strict schema v2 with `fallback_digests`;
- digest coverage is deliberately limited to referenced `index:*` fallbacks and uses SHA-256 over canonical JSON of the presentation-neutral block payload;
- stable `block:*` / `source:*` targets remain unchanged and continue to survive source-preserving reorder;
- exact same-revision index fallback snapshots round-trip, but changed meaning at the numeric fallback now fails explicitly;
- missing/extra digest bindings, non-index digest keys, malformed hex and scalar/container coercion all fail closed;
- schema v1 is explicitly unsupported at restore; any migration remains a persistence-adapter responsibility;
- expanded `tests/test_dev3_bookreader_progress_contract.py` from 8 to 12 deterministic regressions.

No canonical chess legality, GameTree, board, UI, keybinding or NVDA presentation authority was introduced or modified. No test was weakened or skipped.

Terminal executable evidence on `99b5c61c...` through merge ref `c134100d...`:
- diff hygiene PASS;
- compileall PASS;
- focused DEV3 data/reading-progress suite 65/65 PASS;
- full unittest 599/599 PASS;
- full pytest 677 passed + 581 subtests PASS;
- all 12 BookReader progress-contract regressions PASS.

Decision:
- BookReader index-fallback revision-integrity P1 is COMPLETE and exact executable-head GREEN;
- existing DEV3 ACSDB/Library/Search/recovery/query-plan package remains `READY_FOR_INTEGRATION=YES`;
- Training revision-bound snapshot slice remains COMPLETE / GREEN;
- overall DEV3 Full Product mission remains PARTIAL;
- next action after fresh live ownership check: another unclaimed dependency-correct ACSDB/Library/Search or presentation-neutral Books/Training/progress backend P1; remain SAFE OVERLAP if touching work is owned;
- frozen Stage1 release refs untouched;
- fresh Windows candidate: NONE;
- `NVDA_VERIFIED=NO`;
- DEV5/Auditor retain integration/release authority.
