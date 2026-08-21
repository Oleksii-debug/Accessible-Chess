# AUTO-CHESS DEV3 next work

1. Re-read live PR #65/head before any edit and do not overwrite concurrent same-lane DEV3 work.
2. Preserve the verified ACSDB paging/provenance/WAL/scalar package at Product checkpoint `37ab4921f0eff14ba198d9766e37dd6a86898d8d` and exact GREEN run `32527342947`.
3. Next unclaimed READY P1 is bounded large-dataset/query-plan profiling: inspect indexes/query plans for player/event/ECO/opening/source and exact-position searches, add deterministic regressions rather than fabricated latency claims, and avoid accidental full-table materialization.
4. Review higher-level import/export application services for atomicity/provenance only where not already covered by ImportRegistry/PgnFileService/ImportHistoryService. Do not duplicate DEV4 ChessBase decoding/security ownership.
5. Then review engine-assisted training/book/teacher/progress analytics boundaries for concrete DEV3-owned defects only; canonical GameTree/domain stays DEV2-owned and UI stays DEV1-owned.
6. Keep frozen Stage1 release refs untouched. DEV5 owns cross-lane integration/promotion.
7. Every substantial new Product change requires an exact-head terminal CI run before integration readiness is claimed.

Current isolated ACSDB slice: `READY_FOR_INTEGRATION=YES`.
Overall DEV3 Full Product mission: `PARTIAL / CONTINUE ON NEXT SCHEDULED WORK-RUN`.
`NVDA_VERIFIED=NO`.
