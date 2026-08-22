# AUTO-CHESS DEV3 next work

Current executable checkpoint: `85fd447dbc2864fd7e507703aa0c4d342526854f` on `auto/dev3-bookreader-snapshot-bounds-20260822`; draft PR #95.

Current package contracts to preserve:
- BookReader durable return-point count <= 1,000;
- return-point names <= 256 characters before mutation;
- durable semantic target keys <= 4,096 characters before BookIndex resolution;
- fallback-digest map bounded before iteration;
- strict BookReader schema-v2, semantic identity, fallback digest and live-document revision guards remain unchanged;
- StudentProgress snapshot/store resource limits from the prior terminal GREEN package remain unchanged;
- ACSDB Search text terms remain normalized and capped at 256 characters before SQLite execution;
- no duplicate canonical chess/GameTree state, UI state, engine PV or score persistence.

NEXT_ACTION:
1. Re-read PR #95 exact head and exact GitHub Actions evidence first.
2. If CI is RED, inspect the failing step/log and repair Product code; do not weaken assertions or skip tests.
3. If CI is GREEN, record exact run/job/SHA/counts in RUN_STATE, CURRENT_STATE and SESSION_HANDOFF and set this isolated package READY_FOR_INTEGRATION=YES.
4. Only after terminal synchronization, perform a fresh ownership read and claim the next highest-value unowned DEV3 P0/P1 dependency-correct backend package. If touching work is owned or IN_PROGRESS elsewhere, remain SAFE OVERLAP and do non-conflicting evidence/backlog work.

Do not duplicate DEV2 canonical GameTree/domain, DEV1 UI/WebView/Teacher presentation, DEV4 ChessBase/shared PGN-import security, or DEV5 integration/promotion. Frozen Stage1 refs stay untouched. Linux CI is backend evidence only; `NVDA_VERIFIED=NO`.
