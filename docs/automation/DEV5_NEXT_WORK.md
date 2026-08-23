# DEV5_NEXT_WORK

SOURCE_RUN: 20260823-1102
MODE: SAFE_OVERLAP / RELEASE_PRIVACY_REPAIR_FIRST

1. Preserve accepted Stage1 `0fa442330bc2bb03636ff9297512da4c29e38684` and persistent exact-GREEN `dd9ebf9414103c805892856fe6a04706fa69039f`. Do not silently promote any later repair SHA.
2. Read terminal CI for current DEV5-owned PR #151 head first. Current live head is workflow-only follow-up `909d8e2729e00ba5fce0f25a1520010844f9341b`, descended from repair head `f99146f728ace6f76606beeea6caafbb6ac940e9`.
3. Preserve every privacy assertion and frozen-core identity assertion unchanged. The only currently classified Windows failure on `f99146...` was checkout-time CRLF materialization; `909d8e...` rematerializes exact Git bytes after LF config. If the rerun is GREEN, treat this as CI/workflow correction only, not Product semantics.
4. If `909d8e...` is RED, classify the exact failing gate before any Product change. Do not broaden repair scope without machine proof.
5. PR #151 Product scope must remain minimal: safe report-path rendering, Stage1 PGN diagnostics, ImportRegistry mutation/provenance diagnostics, Stockfish startup exception rendering. Preserve exception classes, causal chaining, PGN atomic/concurrency behavior, importer verification, internal paths and safe relative provenance.
6. Only after exact Linux + Windows repair CI is terminal GREEN and diff/oracle review is complete may DEV5 prepare a deliberate promotion decision from `0fa442...` to the repaired Stage1 source. Do not mutate accepted authority by implication.
7. After promotion, run a complete fresh Windows candidate chain. Do not reuse PR #139 artifact state or the rejected ZIP. A new candidate must come from the promoted exact source and a designated exact QA harness SHA.
8. Keep UIA observability investigation separate: `066d1e254c5a2776704bf1f48c580499a24b7045` and prepared V3 `f13f20ca76c8b488447d1996a635df77216397fa` remain untouched. Prior V2 proves Backspace but not Ctrl+A defect.
9. For DEV1-DEV4 next-wave coordination, use only terminal evidence that existed before this run cutoff. Do not consume post-cutoff lane work into directives.
10. DEV4 `3e15dc2e...` remains prior lineage only after PR #146/#147 privacy failures. DEV5 shared-boundary `7c07147...` remains GREEN only for older tested scope.
11. A valid fresh candidate requires one complete GREEN machine chain: exact source lock, frozen core identity, release contracts, WAV assets, official Stockfish, native-menu structural gate, Nuitka standalone build, built-EXE diagnostic, real WebView2 startup, strict UIA interaction, packaged sound/Stockfish lifecycle, release preflight, ZIP reopen/identity, and upload-candidate production.
12. PR #54/frozen refs remain untouched. No skip/xfail/assertion weakening. `NVDA_VERIFIED=NO` until the user personally verifies the exact new candidate.
