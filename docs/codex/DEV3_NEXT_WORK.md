# AUTO-CHESS DEV3 next work

1. Re-read live PR #65/head before any edit and preserve same-lane concurrent progress instead of overwriting it.
2. Preserve verified recovery package head `6c7e9212584ccf6c567d3b9297b7104d73e8b6b1` and exact GREEN run `32527856952`.
3. Next unclaimed P1: bounded large-dataset/query-plan profiling. Use SQLite `EXPLAIN QUERY PLAN`/deterministic evidence, not invented latency. Review source/result/ECO/exact-position/index paths and ensure keyset/LIMIT queries never materialize an entire result set in application memory.
4. Review higher-level import/export application services only for concrete atomicity/provenance gaps not already owned by PgnFileService, ImportRegistry and ImportHistoryService. Do not duplicate DEV4 ChessBase decoding/security work.
5. Then inspect engine-assisted book/training/teacher/progress analytics boundaries for concrete DEV3-owned defects only; canonical GameTree/domain remains DEV2-owned and UI remains DEV1-owned.
6. Keep frozen Stage1 release refs untouched. DEV5 owns cross-lane integration/promotion.
7. Every substantial Product change requires exact-head terminal focused + full executable evidence before readiness is claimed.

Current ACSDB/Library/Search/recovery slice: `READY_FOR_INTEGRATION=YES`.
Overall DEV3 Full Product mission: `PARTIAL / CONTINUE ON NEXT SCHEDULED WORK-RUN`.
`NVDA_VERIFIED=NO`.
