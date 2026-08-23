# DEV5_NEXT_WORK

SOURCE_RUN: 20260823-1158
MODE: SAFE_OVERLAP / RELEASE_PRIVACY_REPAIR_FIRST

1. Preserve accepted Stage1 `0fa442330bc2bb03636ff9297512da4c29e38684` and persistent exact-GREEN `dd9ebf9414103c805892856fe6a04706fa69039f` until explicit promotion.
2. Current DEV5 repair authority-under-review is PR #151 exact head `c0169ed276fff893f90f85192416612f3b998b5a`; exact run `32627628145` is terminal SUCCESS.
3. Do not promote yet. First read terminal evidence from DEV1 QA-only PR #155 exact head `c23c88ac21a6a9c82fad0de4aeadb695f82c5951`, which checks drive-relative Windows private-path forms against `c0169ed...`.
4. Ignore DEV3 PR #156 for authority; it is intentionally superseded by PR #155.
5. If PR #155 is GREEN, independently inspect PR #151 exact diff and oracle scope, then record an explicit Stage1 promotion decision. Do not redefine accepted authority implicitly.
6. If PR #155 is RED, treat the exact failing drive-relative cases as a proven sanitizer defect. Repair only that boundary, preserve safe-relative provenance and every existing privacy assertion, rerun current Linux+Windows privacy/full/release gates and independent oracle.
7. Obsolete `909d8e...` false-GREEN must never be used for promotion. Only current exact repaired head and current oracle suite count.
8. After explicit promotion, execute one completely fresh Windows candidate chain against the promoted exact Product and one designated exact QA harness SHA. Do not silently retarget or reuse old PR #139 artifact state.
9. Keep UIA observability separate. `066d1e254...` and V3 `f13f20ca...` remain untouched; prior V2 proves Backspace but not a Ctrl+A Product defect.
10. Candidate chain must be uninterrupted GREEN through exact source lock, frozen-core identity, release contracts, WAV assets, official Stockfish, native-menu structural gate, Nuitka standalone, built-EXE diagnostic, real WebView2 startup, strict UIA interaction, packaged sound/Stockfish lifecycle, release preflight, ZIP reopen/identity and candidate upload.
11. For DEV1-DEV4 next-wave coordination, consume only terminal evidence existing before 2026-08-23 11:58:14 Europe/Kyiv. Do not race post-cutoff work.
12. DEV2/DEV3 Full Product slices remain later selective backlog; do not contaminate Stage1 release freeze.
13. DEV4 `3e15dc2e...` remains prior lineage only; current Stage1 privacy repair supersedes its incomplete diagnostic privacy scope for release purposes only after explicit promotion.
14. PR #54/frozen refs remain untouched. No force-push shared history, skip, xfail or weakened assertion.
15. Rejected ZIP must not be reused. `NVDA_VERIFIED=NO` until the user personally verifies the exact newly produced candidate.
