# Accessible Chess autonomous next-wave directives

DIRECTIVE_VERSION: 0021
DIRECTIVE_REVISION: 2
ISSUED_BY: DEV5 Coordinator/Integrator
EFFECTIVE_FROM_WAVE: 2026-08-22T19:00:00+03:00
SUPERSEDES_PRE_EFFECTIVE_REVISION: directive 0021 revision 1 issued from the 18:01 coordinator checkpoint
PREVIOUS_DIRECTIVE: 0020 effective 18:00 Europe/Kyiv remains authoritative for workers already running under that snapshot.
SNAPSHOT_SEMANTICS: Every worker takes a fresh immutable cutoff at invocation start. Evidence, CI or terminal handoffs created after that cutoff belong only to a later invocation. Never race or abandon recoverable in-flight work because newer evidence appears.

## GLOBAL BASELINE
Accepted Stage1 remains manual5/integration-20260821 @ 0fa442330bc2bb03636ff9297512da4c29e38684. PR #54/frozen refs remain protected. Old rejected ZIPs remain forbidden.

Current exact-GREEN DEV5 selective validation authority for proved non-PGN full-product scope remains full5/dev5-compose-1700-20260822 @ dd9ebf9414103c805892856fe6a04706fa69039f, draft PR #93 OPEN/MERGEABLE/DO NOT MERGE. Exact CI 32577600761 / 97042099941 SUCCESS: DEV1 focused 111/111; canonical GameTree/BookDocument 22/22; DEV3 focused 53/53; full unittest 789/789; full pytest 867 + 826 subtests; SELFTEST and complete WebView2 diagnostic PASS.

This proves only the selected DEV1 + canonical DEV2 + selected DEV3 non-PGN plane. Shared PGN/ChessBase/import and Windows/release remain separate and blocked.

## DEV1 — DIRECTIVE 0021 R2
Terminal WebView + Teacher WebView Product/test layers through b873e18fe63e7fe9c01518627d33e4b6cc4f8646 are already selectively composed and GREEN. Do not churn them without a concrete combined-validation defect. Preserve one ActionRegistry/router, native editable-control Ctrl+A/C/X/V/Z/Y behavior, route/dialog focus restoration, sanitized errors, and one canonical Teacher provider snapshot for sighted and NVDA projections.

## DEV2 — DIRECTIVE 0021 R2
Canonical full-product core remains 4dd706838881c0e328c7578eada17227de43cf60 and is represented in the GREEN composition. Preserve canonical GameTree/BookDocument/domain authority and CommentStyle.SEMICOLON round-trip semantics. No duplicate core work without a concrete DEV2-owned P0/P1 or independent Audit return.

## DEV3 — DIRECTIVE 0021 R2
At the 18:44 DEV5 cutoff, canonical 12_DEV3_HANDOFF_CURRENT still reported IN_PROGRESS / READY_FOR_INTEGRATION=NO for BookReader durable snapshot resource bounds. Live GitHub subsequently exposed exact observable GREEN evidence for PR #95 head 12763acb772e25524d58d58933a8f65b1f3434ea: DEV3 Full Product ACSDB CI run 32580759442 / job 97049661061 SUCCESS, merge/evidence ref f8c29c8b28fe41c1451621a41f98aa82c6afd342, focused 143/143, full unittest 673/673, full pytest 751 + 628 subtests, SELFTEST and complete WebView2 diagnostic PASS. DEV3 must synchronize canonical RUN_STATE/handoff to this exact evidence and terminal READY_FOR_INTEGRATION=YES before DEV5 intake. PR #95 is evidence-only; do not merge wholesale.

Do not move DEV3 PGN/external-import behavior into DEV5 while shared-boundary repair remains unresolved.

## DEV4 — DIRECTIVE 0021 R2 — HIGHEST PRIORITY SHARED-BOUNDARY PRODUCT REPAIR
Product source remains unchanged at a4209d005ea0a1476f8eafb4822f4d39ac50ee5a. QA PR #67 remains evidence-only. Latest 18:00 QA head c9159bfdba3685112b195b7bbc5ae59210ac4b3a has no observable exact-head Actions, so QA CI remains INCONCLUSIVE, never GREEN.

One coherent DEV4 Product repair, deterministic regressions and observable exact-head CI must close or explicitly reconcile all FOURTEEN locked classes:
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
13. prevent invalid-UTF8 replacement decoding from producing false FULL record-quality counts; lossy source decoding must remain explicit loss/warning evidence in per-record/aggregate quality semantics, preserving tests/test_dev4_pgn_encoding_quality.py;
14. require missing/abrupt PGN game-termination evidence to remain explicit loss/warning evidence rather than silently synthesizing a result and classifying the record FULL, preserving tests/test_dev4_pgn_truncation_quality.py.

Do not weaken QA assertions. Preserve useful error classification without private-detail leakage. Preserve canonical DEV2 GameTree and accepted DEV3 publication semantics. Do not take Windows strict/release ownership.

## REPLACEMENT MANUAL 3DEV
Canonical new handoffs 10_DEVA_HANDOFF_CURRENT, 11_DEVB_HANDOFF_CURRENT and 12_DEVC_HANDOFF_CURRENT were all NOT_STARTED_NEW_3DEV_CHAT at the 18:44 cutoff. Any future worker must re-read them before mutation; if one becomes active, respect its ownership and SAFE OVERLAP.

## DEV5 — DIRECTIVE 0021 R2
At next invocation take a fresh cutoff first. If any touching DEV1/DEV3/DEV4/DEV5 or replacement manual worker is IN_PROGRESS before cutoff, use SAFE OVERLAP only: CI/evidence review, conflict analysis, backlog ordering and directives; no competing Product push.

Preserve dd9ebf9414103c805892856fe6a04706fa69039f as current GREEN non-PGN baseline. Do not independently implement DEV4-owned shared-boundary repairs. Once one terminal DEV4 Product repair with observable exact-head GREEN CI exists, selectively layer only accepted PGN/ChessBase/import Product/tests onto dd9ebf... and run the dedicated vertical PGN -> canonical GameTree -> ACSDB -> Search/Open covering malformed-input atomicity, bounded resources, encoding/truncation quality correctness, no lost updates, batch continuation, path/error privacy, provenance stability, retry/recovery, special-file rejection, signed-64-bit SQLite scalar boundaries, keyboard/focus invariants, full unittest, full pytest, SELFTEST and complete diagnostic.

Persistent shared/full5 authority must not advance beyond exact-SHA GREEN evidence. Evidence PRs remain DO NOT MERGE wholesale. Fresh Windows candidate requires the complete machine release chain on the exact final audited Product SHA. NVDA_VERIFIED remains NO until the user personally verifies that exact candidate.
