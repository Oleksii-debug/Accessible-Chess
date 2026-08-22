# AUTO-CHESS DEV3 next work

Verified checkpoint: Product head `047bdea014964395f95a115fb21cc96c167f3130`, merge/evidence ref `49179718129d102048e9e80500c61a6d93f7b061`, CI run/job `32571453036` / `97027381212` SUCCESS; focused 117/117, unittest 647/647, pytest 725 + 618 subtests, diff/compile/diagnostic PASS.

Preserve these latest contracts:
- engine-assisted Book/Training/Teacher flows reuse the existing `AnalysisService`, never create a second chess/engine authority, sanitize provider failure details, obey exact audience visibility, and suppress stale answers on context drift;
- Student review/progress is append-only, session-sequenced, bounded, strict-schema, concurrency-safe, definition-revision bound, and never persists engine PV/score answer material.

Preserve prior terminal-GREEN ACSDB/Search/recovery/Training/Books contracts and do not weaken tests.

NEXT_ACTION: after the next fresh scheduled ownership read, implement a durable CAS-backed persistence store for `StudentProgressLedger` only if that persistence boundary remains unclaimed; otherwise stay SAFE OVERLAP and produce independent evidence/backlog only.

Do not duplicate DEV2 canonical GameTree/domain, DEV1 UI/Teacher presentation, DEV4 ChessBase/shared PGN-import security, or DEV5 integration/promotion. Frozen Stage1 refs stay untouched. Linux CI is backend evidence only; `NVDA_VERIFIED=NO`.
