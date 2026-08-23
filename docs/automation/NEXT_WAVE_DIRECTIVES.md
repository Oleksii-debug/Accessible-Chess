# NEXT_WAVE_DIRECTIVES

DIRECTIVE_ID: DEV5-1158
REVISION: 1
SOURCE_RUN: 20260823-1158
EFFECTIVE: next worker/DEV5 invocation after 2026-08-23 11:58:14 Europe/Kyiv cutoff.

1. Freeze DEV1-DEV4 coordination intake at this cutoff. Use only terminal evidence that existed before it; do not race in-flight touching work.
2. Accepted Stage1 remains `0fa442330bc2bb03636ff9297512da4c29e38684`; persistent exact-GREEN remains `dd9ebf9414103c805892856fe6a04706fa69039f` until explicit promotion.
3. SAFE OVERLAP remains mandatory because DEV5 already owns touching release-critical Product work in PR #151. Do not create a competing Product repair.
4. Current PR #151 exact repair head is `c0169ed276fff893f90f85192416612f3b998b5a`. `DEV5 Stage1 Path Privacy Repair CI` run `32627628145` is terminal SUCCESS on this exact head.
5. Treat obsolete `909d8e2729e00ba5fce0f25a1520010844f9341b` as superseded; its earlier GREEN is not promotion authority because later independent QA exposed missing batch/OSError coverage.
6. Before any Stage1 promotion, consume terminal verdict from pre-cutoff DEV1 QA-only PR #155, exact head `c23c88ac21a6a9c82fad0de4aeadb695f82c5951`, which probes valid Windows drive-relative private paths against exact `c0169ed...`.
7. DEV3 PR #156 is superseded by PR #155; do not duplicate this evidence surface.
8. If PR #155 is GREEN, independently verify the exact PR #151 Product diff and unchanged/current independent privacy oracles, then record an explicit Stage1 promotion decision. Do not silently redefine accepted authority.
9. If PR #155 is RED, classify it as a proven drive-relative sanitizer gap only. Repair the narrow sanitizer boundary, preserve safe-relative provenance and every existing privacy assertion, then rerun current Linux+Windows privacy/full/release gates and independent evidence before promotion.
10. Preserve PR #151 semantics: report-only private-path redaction, PGN diagnostics, ImportRegistry mutation/provenance/batch rendering, generic Stockfish startup failure text with causal chaining. Do not alter chess state, GameTree, ACSDB, UI, Teacher/Classroom or strict UIA without new machine proof.
11. UIA remains separate: V2 proved original Move Edit and native Backspace `e9 -> e`, then stopped before Ctrl+A on SetValue readback. No Ctrl+A Product defect is proven. Keep `066d1e254...` and V3 `f13f20ca...` untouched unless a deliberate QA ownership decision is made.
12. Only after explicit repaired-Stage1 promotion may one completely fresh Windows candidate chain run. Do not reuse old PR #139 artifact state or rejected ZIP.
13. Candidate validity requires one uninterrupted terminal GREEN chain: exact source lock; frozen-core identity; release contracts; WAV assets; official Stockfish; native-menu structural gate; Nuitka standalone; built-EXE diagnostic; real WebView2 startup; strict UIA; packaged sound/Stockfish lifecycle; release preflight; ZIP reopen/identity; candidate upload.
14. DEV1 source-contract evidence remains useful but is not a candidate substitute. DEV2/DEV3 Full Product slices remain later selective backlog only and must not contaminate the Stage1 freeze.
15. DEV4 `3e15dc2e...` remains prior repair lineage only. Earlier DEV5 shared-boundary GREEN remains valid only for its tested historical scope.
16. PR #54 and frozen refs remain protected. No force-push shared history. No skip/xfail/assertion weakening.
17. `FRESH_WINDOWS_CANDIDATE=NO`, `READY_FOR_RELEASE=NO`, `NVDA_VERIFIED=NO` until the complete fresh machine chain succeeds. `NVDA_VERIFIED` changes only after the user personally verifies that exact artifact.
18. Preserve canonical core, Windows-only direction, native keyboard/menu behavior, focus origin, clipboard invariants, WebView2 boundary, accessibility roles/names/states and fail-closed privacy/security contracts.
19. `AGENTS.md` and `docs/codex/*` remain absent on live default branch at this cutoff. Use live GitHub SHA/diff/tests/CI plus versioned `docs/automation/*` unless those canonical files later appear and are verified.
