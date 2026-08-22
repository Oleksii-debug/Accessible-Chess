# AUTO-CHESS DEV3 next work

Verified checkpoint: executable Product head `4c0f5885e51aa93ad366dccaf61a962c930f5ef0`, PR merge/evidence ref `10598ff59d984d788dc303ce6bd4a8eec797b445`, CI run/job `32577628215` / `97042172326` SUCCESS; focused 134/134, unittest 664/664, pytest 742 + 628 subtests, diff/compile/diagnostic PASS.

Preserve these latest contracts:
- StudentProgress snapshot restore is bounded to 50,000 records before iteration;
- StudentProgressStore physical reads are bounded to 16 MiB + 1 and oversized files fail closed on load and CAS save checks;
- newly serialized StudentProgress payloads above 16 MiB fail before temp-file publication;
- strict schema-v1, append-only identity/order, exact SHA-256 CAS, create-only first save, peer locking and atomic publication remain unchanged;
- no duplicate canonical chess state, UI state, engine PV or score is persisted;
- ACSDB Library/Search text filters remain normalized then capped at 256 characters before SQLite execution, with literal LIKE escaping and stable keyset paging preserved;
- prior engine-assisted Book/Training/Teacher flows continue to reuse the existing AnalysisService and suppress stale/private answer material.

Preserve all prior terminal-GREEN ACSDB/Search/recovery/Training/Books/Student contracts and do not weaken tests.

NEXT_ACTION: perform a fresh live ownership and coordination read. Claim only the highest-value unowned DEV3 P0/P1 dependency-correct backend slice. Prefer ACSDB/Library/Search or presentation-neutral engine/Training/Books/Student infrastructure that composes with the single canonical core. If touching work is already IN_PROGRESS or owned by another lane, remain SAFE OVERLAP and produce non-conflicting tests/evidence/backlog refinement instead.

Do not duplicate DEV2 canonical GameTree/domain, DEV1 UI/Teacher presentation, DEV4 ChessBase/shared PGN-import security, or DEV5 integration/promotion. Frozen Stage1 refs stay untouched. Linux CI is backend evidence only; `NVDA_VERIFIED=NO`.
