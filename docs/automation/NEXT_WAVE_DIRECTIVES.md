# Accessible Chess autonomous next-wave directives

DIRECTIVE_VERSION: 0021
ISSUED_BY: DEV5 Coordinator/Integrator
EFFECTIVE_FROM_WAVE: 2026-08-22T19:00:00+03:00
PREVIOUS_DIRECTIVE: 0020 effective 18:00 Europe/Kyiv remains authoritative for workers already running under that snapshot.
SNAPSHOT_SEMANTICS: Every worker takes a fresh immutable cutoff at invocation start. Evidence, CI or terminal handoffs created after that cutoff belong only to a later invocation. Never race or abandon recoverable in-flight work because newer evidence appears.

## GLOBAL BASELINE
Accepted Stage1 integration remains manual5/integration-20260821 @ 0fa442330bc2bb03636ff9297512da4c29e38684. PR #54/frozen refs remain protected. Old rejected ZIPs remain forbidden.

Current exact-GREEN DEV5 selective validation authority for the proved non-PGN full-product scope remains:
- branch full5/dev5-compose-1700-20260822
- source head dd9ebf9414103c805892856fe6a04706fa69039f
- draft PR #93 OPEN/MERGEABLE/DRAFT/DO NOT MERGE
- exact base 7f4d2af3447d8d5046c9a75e1243a4ce36b11e4a
- merge/evidence ref 98d04a0463ff9712113c642fe8f4688f4da175e6
- DEV5 CI 32577600761 / 97042099941 SUCCESS
- DEV1 WebView/accessibility focused 111/111 PASS
- canonical GameTree/BookDocument 22/22 PASS
- DEV3 data/progress/search/engine-assisted focused 53/53 PASS
- full unittest 789/789 PASS
- full pytest 867 PASS + 826 subtests PASS
- SELFTEST and complete WebView2 diagnostic PASS.

This authority proves only the selected DEV1 + canonical DEV2 + selected DEV3 non-PGN plane. Shared PGN/ChessBase/import and Windows/release remain separate and blocked.

## DEV1 — DIRECTIVE 0021
Terminal WebView + Teacher WebView Product/test layers through b873e18fe63e7fe9c01518627d33e4b6cc4f8646 are already selectively composed and GREEN in DEV5 PR #93. Do not churn them without a concrete combined-validation defect. Preserve one ActionRegistry/router, native editable-control Ctrl+A/C/X/V/Z/Y behavior, route/dialog focus restoration, sanitized errors, and one canonical Teacher provider snapshot for both sighted and NVDA projection.

## DEV2 — DIRECTIVE 0021
Canonical full-product core remains 4dd706838881c0e328c7578eada17227de43cf60 and is represented in the GREEN composition. Preserve canonical GameTree/BookDocument/domain authority and CommentStyle.SEMICOLON round-trip semantics. No duplicate core work without a concrete DEV2-owned P0/P1 or independent Audit return.

## DEV3 — DIRECTIVE 0021
Terminal cumulative non-PGN backend through 6f90516a8beefa8c191a8c593aaf3f2e410aa738 remains selectively composed and GREEN. Preserve presentation-neutral ownership, stale engine suppression, no persisted engine PV/score material, append-only Student progress identity, CAS/no-lost-update progress storage and the 256-character normalized search bound. Do not move DEV3 PGN/external-import behavior into DEV5 while shared-boundary repair remains unresolved.

## DEV4 — DIRECTIVE 0021 — HIGHEST PRIORITY SHARED-BOUNDARY PRODUCT REPAIR
Product source remains unchanged at a4209d005ea0a1476f8eafb4822f4d39ac50ee5a. QA branch qa/dev4-chessbase-symlink-security-20260822 is evidence-only; exact QA head 588462042befb0be3f68aca34fee407716a3aed5 still has no observable exact-head Actions, therefore QA CI remains INCONCLUSIVE, never GREEN.

One coherent DEV4 Product repair, deterministic regressions and observable exact-head CI must close or explicitly reconcile all THIRTEEN locked classes:
1. reject import/ChessBase symlink/reparse indirection;
2. enforce bounded PGN reads and finite source-size limits;
3. prevent serialized local-path leakage;
4. close expected_sha256 commit-boundary TOCTOU;
5. make overwrite=False safe against competing creators;
6. reject PGN export filesystem-indirection/symlink escape;
7. distinguish companion-directory I/O failure from ordinary no-companion evidence;
8. make ImportRegistry.inspect_batch record importer RuntimeError and continue later inputs;
9. convert manifest/integrity hash/open OSError/PermissionError into explicit domain-safe failed verification;
10. reject FIFO/device-like/non-regular inputs before any ordinary fingerprint open;
11. make provenance hashing stable against concurrent same-size mutation across BOTH shared import_contract.fingerprint() and ChessBase integrity fingerprint paths;
12. redact/safely classify failed ACSDB import diagnostics before persistence/application exposure so private paths, token-like provider detail and raw exception internals do not cross import-history boundaries;
13. prevent invalid-UTF8 replacement decoding from producing false FULL record-quality counts: lossy source decoding must remain explicit loss/warning evidence in per-record/aggregate quality semantics, with strict gate tests/test_dev4_pgn_encoding_quality.py preserved.

Do not weaken QA assertions. Preserve useful error classification without private-detail leakage. Preserve canonical DEV2 GameTree and accepted DEV3 publication semantics. Do not take Windows strict/release ownership.

## DEV5 — DIRECTIVE 0021
At next invocation take a fresh cutoff first. If any touching DEV1/DEV3/DEV4/DEV5 or replacement manual worker is IN_PROGRESS before cutoff, use SAFE OVERLAP only: CI/evidence review, conflict analysis, backlog ordering and directives; no competing Product push.

If no touching worker is active, preserve dd9ebf9414103c805892856fe6a04706fa69039f as the current GREEN non-PGN baseline. The shared PGN/ChessBase/import repair remains DEV4-owned, so DEV5 must not independently implement the thirteen repairs merely because DEV4 is temporarily terminal.

Once DEV4 supplies one terminal Product repair with observable exact-head GREEN CI, DEV5 may selectively layer ONLY accepted shared-boundary Product/tests onto dd9ebf... lineage and run a dedicated vertical:
PGN -> canonical GameTree -> ACSDB -> Search/Open
covering malformed-input atomicity, bounded resources, lossy-encoding quality accounting, no lost updates, batch continuation, path/error privacy, provenance stability, retry/recovery, special-file rejection, signed-64-bit SQLite scalar boundaries, keyboard/focus invariants, full unittest, full pytest and complete diagnostic.

Persistent shared-boundary/full5 authority must not advance beyond exact-SHA GREEN evidence. Evidence PRs remain DO NOT MERGE wholesale. Fresh Windows candidate requires the complete machine release chain on the exact final audited Product SHA. NVDA_VERIFIED remains NO until the user personally verifies that exact candidate.
