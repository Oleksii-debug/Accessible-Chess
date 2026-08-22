# AUTO-CHESS DEV3 current state

Lane: Full Product engine/analysis + ACSDB / Library / Search / import-export storage safety.

Active branch: `auto/dev3-acsdb-stable-paging-20260821`
Draft PR: #65 against `codex/full-product-20260821`

Latest verified executable package head before documentation-only synchronization: `24817c894fd84cdf0b8e63391249a95c09718e6a`.
Exact CI run/job: `32539307522` / `96945995146` — SUCCESS.
PR merge ref executed by the workflow: `44e04d6d761f692d6e13ca4b9e2fcc5ca2f7be51` against Full Product base `656e8ec311e364e6e54a30504fd30a4aaff586f9`.
Runner evidence: GitHub runner `2.336.0`, `ubuntu-24.04@20260816.277.1`, Python 3.12.14.

Verified DEV3 package includes:
- stable keyset paging for games, import attempts and exact-position `(game_id, ply)` results;
- source provenance on game and position result rows;
- schema v3 composite exact-position index;
- WAL + 5000 ms busy timeout for file-backed databases after supported-schema migration;
- strict no-coercion query cursor/limit contracts through ACSDB, GameSearchService and ImportHistoryService;
- deterministic large-dataset paging with no duplicate ids;
- v2->v3 migration preservation and WAL reader/writer concurrency coverage;
- consistent SQLite backup via native backup API, integrity validation and peer-temp publication;
- query-plan evidence over large deterministic datasets and the 1,000-row public search bound;
- PGN no-overwrite publication uses atomic same-directory create-if-absent semantics and preserves a concurrent creator;
- ACSDB `backup_to()` and `restore_backup()` now also publish `overwrite=False` via atomic same-directory `os.link()` create-if-absent rather than a final existence check followed by unconditional `os.replace()`;
- explicit `overwrite=True` for ACSDB backup/restore retains atomic replacement semantics;
- deterministic backup and restore regressions force a competing creator into the final publication window, prove competitor bytes survive, and prove peer-temp cleanup.

Exact CI evidence on `24817c8...`:
- diff hygiene PASS;
- compileall PASS;
- focused ACSDB/position/WAL/recovery/query-plan suite: 36/36 PASS;
- full unittest discovery: 575/575 PASS;
- full pytest: 653 passed + 545 subtests passed;
- both new ACSDB publication-race tests PASS;
- no tests weakened/skipped for GREEN.

Live ownership / SAFE OVERLAP:
- DEV2 remains owner of canonical GameTree/domain work; no GameTree/chess-rule source changed here.
- DEV1 owns presentation/UI and Teacher presentation surfaces.
- DEV4 QA PR #67 independently owns symlink/reparse, unbounded-PGN-resource, ChessBase report-path privacy and its separate PGN optimistic-concurrency security evidence; this DEV3 ACSDB slice does not claim or alter those findings.
- DEV5 owns cross-lane integration/promotion.

Readiness:
- Stage1 engine backend: COMPLETE / already accepted downstream; `NVDA_VERIFIED=NO`.
- DEV3 ACSDB/Library/Search/recovery/query-plan package: `READY_FOR_INTEGRATION=YES`.
- PGN no-overwrite lost-update slice: COMPLETE / GREEN.
- ACSDB backup/restore no-overwrite final-publication race slice: COMPLETE / exact-head GREEN.
- Overall DEV3 Full Product mission: PARTIAL.
- Next action: re-read live ownership, then take the next unclaimed DEV3 backend P1 in training/progress analytics or another dependency-correct ACSDB/Library/Search boundary. Do not duplicate DEV2 canonical GameTree, DEV1 presentation, DEV4 QA/security or DEV5 integration work.
- Frozen release refs untouched; no Windows candidate created; DEV5/Auditor retain integration/release authority.
