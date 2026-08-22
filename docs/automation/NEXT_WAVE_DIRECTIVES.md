# Accessible Chess autonomous next-wave directives

DIRECTIVE_VERSION: 0016
ISSUED_BY: DEV5 Coordinator/Integrator
EFFECTIVE_FROM_WAVE: 2026-08-22T15:00:00+03:00
SNAPSHOT_SEMANTICS: Workers already running before the effective wave must ignore this directive until their next invocation. Never abandon recoverable in-flight work because a newer directive appears.

## GLOBAL SNAPSHOT
Accepted Stage1 integration remains manual5/integration-20260821 @ 0fa442330bc2bb03636ff9297512da4c29e38684. PR #54/frozen refs remain protected. No Stage1 churn.

DEV5 validation branch full5/dev5-selective-compose-20260822 now proves a selective DEV1 + canonical DEV2 + selected DEV3 full-product plane composes GREEN on accepted Stage1. Final validation head 7f4d2af3447d8d5046c9a75e1243a4ce36b11e4a; draft PR #88 DO NOT MERGE. Exact DEV5 CI 32569504104 / job 97022845834 SUCCESS: DEV1 accessibility 78/78; GameTree/BookDocument 22/22; full unittest 718/718; full pytest 796 + 791 subtests; SELFTEST and full WebView2 diagnostic PASS.

## DEV1 — DIRECTIVE 0016
Terminal package 995f7846a56d7f52e6403544046da11e6d061c1c has been selectively composed by DEV5 and is GREEN in combined validation. Do not churn the same presentation/action/focus files unless DEV5 or a fresh audit identifies a concrete defect. Preserve canonical GameTree/backend ownership and all keyboard/focus/NVDA invariants.

## DEV2 — DIRECTIVE 0016
Canonical GameTree/BookDocument/interaction package 4dd706838881c0e328c7578eada17227de43cf60 has been selectively composed by DEV5 and is GREEN. The semicolon-comment contract is now explicitly preserved as CommentStyle.SEMICOLON; do not regress it to brace normalization. No duplicate GameTree churn unless a concrete combined-validation defect appears.

## DEV3 — DIRECTIVE 0016
Selected exact data/progress package from eligible terminal checkpoint 51d77c4c6f6a70cd47ffb772fff476ce9480d135 is GREEN in DEV5 combined validation. ACSDB/SearchService/BookReader/Training/TrainingProgressStore/ImportHistoryService are accepted for continued validation. Do not push PGN/external-import behavior into DEV5 composition until DEV4 blockers are resolved. Synchronize canonical handoff before another moving continuation.

## DEV4 — DIRECTIVE 0016 — HIGHEST PRIORITY
Close or explicitly reconcile the ten locked PGN/ChessBase/import defects with deterministic regressions and observable exact-head CI:
1. reject symlink/reparse import indirection;
2. enforce bounded PGN reads and finite source-size limits;
3. prevent serialized local-path leakage;
4. close expected_sha256 commit-boundary TOCTOU;
5. make overwrite=False safe against competing creators;
6. reject PGN export filesystem-indirection/symlink escape;
7. distinguish companion-directory I/O failure from ordinary no-companion evidence;
8. make ImportRegistry.inspect_batch record importer RuntimeError and continue later sources;
9. convert manifest hash/open OSError/PermissionError into explicit failed verification;
10. validate regular-file type before fingerprinting so FIFO/device-like special files are never opened as normal imports.
Do not weaken tests. Preserve canonical DEV2 GameTree and selected DEV3 publication/provenance semantics. Do not touch Windows strict/release-owner lanes.

## DEV5 — DIRECTIVE 0016
At next invocation take a fresh cutoff first. If a touching DEV4 Product fix is IN_PROGRESS, enter SAFE OVERLAP and do evidence/conflict preparation only. Once terminal DEV4 fixes exist, layer only those repaired PGN/import boundaries onto validation branch lineage and run a dedicated PGN -> canonical GameTree -> ACSDB -> search/open vertical matrix covering malformed-input atomicity, bounded resources, no lost updates, batch continuation, path privacy/provenance, retry/recovery, special-file rejection, signed-64-bit SQLite bounds, keyboard/focus invariants, full unittest, full pytest and complete diagnostic.

Persistent full5 integration authority must not be promoted until the repaired vertical path is exact-SHA GREEN. Draft PR #88 remains validation evidence only. Never merge evidence PRs wholesale.

Rejected ZIPs are never reused. Fresh Windows candidate requires the complete machine release chain on the exact final audited Product SHA. NVDA_VERIFIED remains NO until the user personally verifies that exact candidate.
