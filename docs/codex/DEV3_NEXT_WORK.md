# AUTO-CHESS DEV3 next work

Verified checkpoint: executable Product head `6160d02b22c0a911082a3896f3fc9b09f5edd1b0`, PR merge/evidence ref `9f90dc0839a16ee16fd61c2910bd12e419b8759e`, CI run/job `32571958759` / `97028547641` SUCCESS; focused 125/125, unittest 655/655, pytest 733 + 618 subtests, diff/compile/diagnostic PASS.

Preserve these latest contracts:
- durable Student progress persistence wraps the existing `StudentProgressLedger`; it does not become a second domain authority;
- first save is create-only, updates require the exact previously observed SHA-256 revision, stale writers fail closed, and peer lock + atomic publication protect concurrent writes;
- restore remains strict-schema and delegates review identity/order validation to the ledger;
- persisted Student analytics never contains engine PV/score answer material or canonical chess/UI state;
- prior engine-assisted Book/Training/Teacher flows reuse the existing `AnalysisService` and suppress stale/private answer material correctly.

Preserve all prior terminal-GREEN ACSDB/Search/recovery/Training/Books contracts and do not weaken tests.

NEXT_ACTION: perform a fresh live ownership and coordination read. Claim only the highest-value unowned DEV3 P0/P1 dependency-correct backend slice. Prefer ACSDB/Library/Search or presentation-neutral engine/Training/Books/Student infrastructure that composes with the single canonical core. If touching work is already IN_PROGRESS or owned by another lane, remain SAFE OVERLAP and produce non-conflicting tests/evidence/backlog refinement instead.

Do not duplicate DEV2 canonical GameTree/domain, DEV1 UI/Teacher presentation, DEV4 ChessBase/shared PGN-import security, or DEV5 integration/promotion. Frozen Stage1 refs stay untouched. Linux CI is backend evidence only; `NVDA_VERIFIED=NO`.
