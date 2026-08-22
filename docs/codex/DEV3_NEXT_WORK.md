# AUTO-CHESS DEV3 next work

Verified checkpoint: executable Product head `6f90516a8beefa8c191a8c593aaf3f2e410aa738`, PR merge/evidence ref `4bab8883cd293a0aa25d2a39d92e3a1abd4f6ff1`, CI run/job `32574651690` / `97035089135` SUCCESS; focused 130/130, unittest 660/660, pytest 738 + 628 subtests, diff/compile/diagnostic PASS.

Preserve these latest contracts:
- ACSDB Library/Search text filters are normalized then capped at 256 characters before SQLite execution;
- literal `%`, `_`, and backslash search semantics remain escaped rather than wildcard-expanded;
- strict no-coercion query scalars, stable keyset paging, provenance and prior query-plan guarantees remain unchanged;
- durable Student progress persistence continues to wrap the existing `StudentProgressLedger`; it does not become a second domain authority;
- prior engine-assisted Book/Training/Teacher flows reuse the existing `AnalysisService` and suppress stale/private answer material correctly.

Preserve all prior terminal-GREEN ACSDB/Search/recovery/Training/Books/Student contracts and do not weaken tests.

NEXT_ACTION: perform a fresh live ownership and coordination read. Claim only the highest-value unowned DEV3 P0/P1 dependency-correct backend slice. Prefer ACSDB/Library/Search or presentation-neutral engine/Training/Books/Student infrastructure that composes with the single canonical core. If touching work is already IN_PROGRESS or owned by another lane, remain SAFE OVERLAP and produce non-conflicting tests/evidence/backlog refinement instead.

Do not duplicate DEV2 canonical GameTree/domain, DEV1 UI/Teacher presentation, DEV4 ChessBase/shared PGN-import security, or DEV5 integration/promotion. Frozen Stage1 refs stay untouched. Linux CI is backend evidence only; `NVDA_VERIFIED=NO`.
