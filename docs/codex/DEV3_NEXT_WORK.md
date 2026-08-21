# AUTO-CHESS DEV3 next work

1. Re-read live PR #65 and exact branch head before any new edit.
2. Obtain observable executable evidence for the current ACSDB package. Preferred proof: branch `DEV3 Full Product Data CI` with focused `tests.test_acsdb` + `tests.test_dev3_acsdb_position_provenance` and full `unittest discover` terminal results.
3. If that CI is not observable through the current connector, validate the exact Product/test checkpoint in the first repository-capable runner; do not infer GREEN from mergeability or static inspection.
4. If tests expose a regression, fix the root cause without weakening coverage and preserve the backward-compatible `search_position(fen, limit)` call shape.
5. Only after terminal executable evidence, consider the next unclaimed ACSDB/Library/Search P1: large-dataset query/index profiling, provenance-facing library adapters, or atomic cross-read/import consistency.
6. Do not merge or retarget frozen Stage1 release refs. DEV5 may integrate only after exact evidence is terminal.

Current integration readiness: `READY_FOR_INTEGRATION=NO` pending observable executable test/CI evidence.
`NVDA_VERIFIED=NO`.
