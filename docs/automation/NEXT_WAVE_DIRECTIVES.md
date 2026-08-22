# Accessible Chess autonomous next-wave directives

DIRECTIVE_VERSION: 0023
DIRECTIVE_REVISION: 1
ISSUED_BY: DEV5 Coordinator/Integrator
ISSUED_FROM_CUTOFF: 2026-08-22T19:57:32+03:00
EFFECTIVE_FROM_WAVE: 2026-08-22T21:00:00+03:00
SNAPSHOT_SEMANTICS: Each worker consumes only terminal evidence that existed before its own invocation cutoff. If touching same-lane/integration work is IN_PROGRESS, enter SAFE OVERLAP and do not create competing Product pushes.

GLOBAL: accepted Stage1 remains `manual5/integration-20260821 @ 0fa442330bc2bb03636ff9297512da4c29e38684`. Persistent GREEN DEV5 composition remains `full5/dev5-compose-1700-20260822 @ dd9ebf9414103c805892856fe6a04706fa69039f`, PR #93 DRAFT/DO NOT MERGE, CI `32577600761 / 97042099941` SUCCESS. PR #54/frozen refs protected. Rejected ZIP forbidden. Fresh Windows candidate NONE. `NVDA_VERIFIED=NO`.

DEV1: terminal pre-cutoff classroom/remote WebView head is `6b3e41f6c7bf0a436d70c9926e3761cc7f99260f`; exact-source validation is GREEN. Preserve prior shell/Teacher/WebView semantics; take only unowned UI/accessibility work and never duplicate canonical backend state.

DEV2: terminal canonical head is `371417c2ef43f35da99e6f6ea0bab09e2bae68bb`. Evidence-only PR #104 is GREEN but must not be merged wholesale. Preserve canonical GameTree, strict snapshot/JSON exchange, PGN termination-loss evidence, deterministic remote-session replay and bounded/corruption-rejecting semantics.

DEV3: terminal coordination head is `1dd2e9d69136a801b7943c1ee2a8b4df6d5e44f7` with exact final-head GREEN evidence through PR #103. Reconcile BookReader durable bounds, bounded cancellable GameReview, StudentProgress persistence/search bounds, and direct AnalysisService FEN bounds as one provenance-aware lineage; no parallel chess/UI/import ownership.

DEV4: highest shared risk. PR #100 head `41fee6049d045e847a72cc4c6452618e6b52ac83` remains Product-repair WIP and exact-head CI is INCONCLUSIVE. Finish only proven shared-boundary defects. In particular close remaining ACSDB failed-import error privacy, PGN export destination/path-indirection safety, expected_sha256 commit-boundary lost-update race and overwrite=False commit-boundary clobber race. Preserve prior repairs for special-file/symlink rejection, stable provenance snapshots, 64 MiB PGN bounds, invalid-UTF8 quality downgrade, batch continuation, ChessBase path privacy/I/O observability, and DEV2 missing-termination-marker loss evidence. Do not weaken QA.

DEV5: take a fresh cutoff. If any touching work is active, SAFE OVERLAP only. Once all required lane handoffs are terminal and DEV4 exact-head Product evidence is GREEN, create a disposable selective composition from `dd9ebf...`; never wholesale-merge evidence PR histories. Run PGN -> canonical GameTree -> ACSDB -> Search/Open plus malformed/oversized/encoding/truncation/concurrency/path/privacy/provenance/recovery/SQLite-bound/remote-session and keyboard/focus/clipboard/Teacher non-mutation gates; then full unittest, full pytest, SELFTEST and complete WebView2 diagnostic. Persistent full5 authority advances only after exact combined GREEN.

Fresh Windows candidate requires the complete machine release chain on the exact final audited Product SHA. `NVDA_VERIFIED` remains NO until Oleksii personally verifies that exact candidate.
