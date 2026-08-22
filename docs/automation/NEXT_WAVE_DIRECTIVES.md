# Accessible Chess autonomous next-wave directives

DIRECTIVE_VERSION: 0017
ISSUED_BY: DEV5 Coordinator/Integrator
EFFECTIVE_FROM_WAVE: 2026-08-22T15:00:00+03:00
SUPERSEDES_BEFORE_ACTIVATION: 0016
SNAPSHOT_SEMANTICS: Workers already running before the effective wave must ignore this directive until their next invocation. Never abandon recoverable in-flight work because a newer directive appears.

## GLOBAL SNAPSHOT
Accepted Stage1 integration remains manual5/integration-20260821 @ 0fa442330bc2bb03636ff9297512da4c29e38684. PR #54/frozen refs remain protected. No Stage1 churn.

DEV5 validation branch full5/dev5-selective-compose-20260822 remains exact 7f4d2af3447d8d5046c9a75e1243a4ce36b11e4a; draft PR #88 DO NOT MERGE. Exact DEV5 Full Product Selective Composition CI 32569504104 / 97022845834 is SUCCESS: DEV1 accessibility 78/78; canonical GameTree/BookDocument 22/22; full unittest 718/718; full pytest 796 + 791 subtests; SELFTEST and complete WebView2 diagnostic PASS.

This proves the selected DEV1 + canonical DEV2 + selected DEV3 plane composes cleanly. It does NOT authorize PGN/ChessBase/import promotion or persistent full5 authority.

## DEV1 — DIRECTIVE 0017
Terminal exact Product package 995f7846a56d7f52e6403544046da11e6d061c1c is already selectively represented and GREEN in DEV5 PR #88. Do not churn the same presentation/action/focus files without a concrete combined-validation defect. Preserve one ActionRegistry, standard editable-control shortcuts, focus restoration, sanitized user errors and external canonical Teacher/backend authority.

## DEV2 — DIRECTIVE 0017
Canonical full-product GameTree/BookDocument package 4dd706838881c0e328c7578eada17227de43cf60 is terminal and already selectively represented in PR #88. Preserve CommentStyle.SEMICOLON round-trip semantics and accepted DEV1 rank/file/keybinding actions. Do not duplicate GameTree/domain churn without a concrete defect.

## DEV3 — DIRECTIVE 0017
Canonical handoff is synchronized to exact selected Product head 51d77c4c6f6a70cd47ffb772fff476ce9480d135 with exact DEV3 CI 32568754137 / 97021116904 SUCCESS. ACSDB/Search/BookReader/Training/TrainingProgress/ImportHistory selected contracts are already GREEN in DEV5 combined validation. Do not push DEV3 PGN/external-import behavior into the DEV5 lineage until DEV4 Product security/concurrency repair is terminal and accepted.

## DEV4 — DIRECTIVE 0017 — HIGHEST PRIORITY PRODUCT REPAIR
The eligible pre-15:00 snapshot contains eleven proven PGN/ChessBase/import defect classes. Create a coherent Product repair package, not QA-only evidence, with deterministic regressions and observable exact-head CI. Close or explicitly reconcile all eleven:
1. reject symlink/reparse import indirection;
2. enforce bounded PGN reads and finite source-size limits;
3. prevent serialized local-path leakage;
4. close expected_sha256 commit-boundary TOCTOU;
5. make overwrite=False safe against competing creators;
6. reject PGN export filesystem-indirection/symlink escape;
7. distinguish companion-directory I/O failure from ordinary no-companion evidence;
8. make ImportRegistry.inspect_batch record importer RuntimeError and continue later sources;
9. convert manifest hash/open OSError/PermissionError into explicit failed verification;
10. validate regular-file type before fingerprinting so FIFO/device-like sources are never opened as normal imports;
11. make SourceFingerprint collection stable against concurrent mutation during hashing, rejecting mixed/stale snapshots even when size is unchanged.

Do not weaken strict QA assertions. Preserve canonical DEV2 GameTree and selected DEV3 publication/provenance semantics. Do not take over Windows strict/release-owner lanes. Exact-head absence is INCONCLUSIVE, never GREEN. Any evidence created after another worker's invocation cutoff belongs to that worker's next fresh snapshot, not retroactive coordination.

## DEV5 — DIRECTIVE 0017
At next invocation take a fresh cutoff first. If a touching DEV4 Product repair is IN_PROGRESS before cutoff, enter SAFE OVERLAP and perform evidence/conflict preparation only. Once a terminal DEV4 repair exists with observable exact-head CI, selectively layer only repaired PGN/import boundaries onto the existing GREEN 7f4d2af... lineage.

Then run a dedicated vertical matrix:
PGN -> canonical GameTree -> ACSDB -> Search/Open
covering malformed-input atomicity, bounded resources, no lost updates, batch continuation, private-path/error sanitization, provenance stability, retry/recovery, special-file rejection, signed-64-bit SQLite scalar boundaries, keyboard/focus invariants, full unittest, full pytest and complete diagnostic.

Persistent full5 integration authority must not advance until that repaired vertical is exact-SHA GREEN with auditable provenance. Evidence PRs remain DO NOT MERGE wholesale.

Rejected ZIPs are never reused. Fresh Windows candidate requires the complete machine release chain on the exact final audited Product SHA. NVDA_VERIFIED remains NO until the user personally verifies that exact candidate.
