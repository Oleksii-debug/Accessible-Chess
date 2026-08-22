# Accessible Chess autonomous next-wave directives

DIRECTIVE_VERSION: 0019
ISSUED_BY: DEV5 Coordinator/Integrator
EFFECTIVE_FROM_WAVE: 2026-08-22T17:00:00+03:00
PREVIOUS_DIRECTIVE: 0018 effective 16:00 Europe/Kyiv remains authoritative for workers already running under that snapshot.
SNAPSHOT_SEMANTICS: Every worker takes a fresh immutable cutoff at invocation start. Evidence, CI or terminal handoffs created after that cutoff belong only to a later invocation. Never race or abandon recoverable in-flight work because newer evidence appears.

## GLOBAL BASELINE
Accepted Stage1 integration remains manual5/integration-20260821 @ 0fa442330bc2bb03636ff9297512da4c29e38684. PR #54/frozen refs remain protected. Old rejected ZIPs remain forbidden.

DEV5 exact-GREEN full-product validation baseline remains full5/dev5-selective-compose-20260822 @ 7f4d2af3447d8d5046c9a75e1243a4ce36b11e4a, PR #88 OPEN/DRAFT/DO NOT MERGE. Exact DEV5 CI 32569504104 / 97022845834 SUCCESS: DEV1 78/78; canonical GameTree/BookDocument 22/22; unittest 718/718; pytest 796 + 791 subtests; SELFTEST and complete WebView2 diagnostic PASS.

The 16:02 DEV5 wave stayed SAFE OVERLAP because canonical DEV3 Drive state was already IN_PROGRESS at 16:02:16, before its 16:02:34 cutoff. No Product change was made.

## DEV1 — DIRECTIVE 0019
Latest eligible terminal cumulative presentation chain now reaches branch full5/dev1-teacher-webview-20260822-1538 @ b873e18fe63e7fe9c01518627d33e4b6cc4f8646, PR #91 OPEN/DRAFT/DO NOT MERGE WHOLESALE.

Dependency order for future selective intake:
1. prior terminal full-product WebView adapter layer through 98ad9347d1a4e4a4c6bf766b93146f380675d471;
2. Teacher WebView projection layer through b873e18fe63e7fe9c01518627d33e4b6cc4f8646.

Latest increment is only acs/teacher_webview_projection.py, tests/test_dev1_teacher_webview_projection.py and workflow metadata. Exact CI 32573762014 / 97032967628 SUCCESS: focused 79/79; canonical service + Stage1 accessibility 65/65; unittest 690/690; pytest 768 + 713 subtests; diagnostic PASS. Preserve the fixed invariant that sighted visual Teacher projection and blind/NVDA textual summary derive atomically from the SAME canonical presentation snapshot. Do not reintroduce duplicate chess/Teacher authority. DEV5 may selectively consume Product/tests on a no-overlap cutoff; do not merge PR #89/#91 wholesale.

## DEV2 — DIRECTIVE 0019
No new Product work. RUN_STATE 20260822-1538 is COMPLETE / NO_PRODUCT_MUTATION. Canonical full-product head 4dd706838881c0e328c7578eada17227de43cf60 remains represented in DEV5 GREEN validation with exact CI 32565884179 / 97014330560 SUCCESS. Preserve canonical GameTree/BookDocument semantics, CommentStyle.SEMICOLON round-trip and accepted DEV1 action/keybinding contracts. Resume only for a concrete DEV2-owned P0/P1 or independent Audit return.

## DEV3 — DIRECTIVE 0019
The 16:02 cutoff captured DEV3 already IN_PROGRESS on auto/dev3-search-resource-bounds-20260822. Therefore the prior terminal StudentProgressStore package and the newer search resource-bound package were not composed by DEV5 in that wave.

Known terminal backlog before that cutoff:
- PR #90 executable Product head 6160d02b22c0a911082a3896f3fc9b09f5edd1b0;
- CI 32571958759 / 97028547641 SUCCESS;
- focused 125/125, unittest 655/655, pytest 733 + 618 subtests, diagnostic PASS;
- durable CAS StudentProgressStore only; no shared PGN/import ownership.

Observed AFTER the 16:02:34 cutoff, for fresh re-evaluation only:
- PR #92 head 6f90516a8beefa8c191a8c593aaf3f2e410aa738;
- exact CI 32574651690 started 16:02:47 and completed SUCCESS;
- focused 130/130, unittest 660/660, pytest 738 + 628 subtests, diagnostic PASS;
- new Product delta isolates to acs/search_service.py and bounds normalized user search text to 256 characters before SQLite execution.

At the next invocation, fresh-snapshot canonical DEV3 handoff/run state. If any touching DEV3 continuation is IN_PROGRESS before cutoff, do not consume any descendant Product state. If terminal, selectively intake only dependency-correct Product/tests in lineage order and exclude workflow/docs metadata and shared PGN/import paths. Never merge PR #90/#92 wholesale.

## DEV4 — DIRECTIVE 0019 — HIGHEST PRIORITY SHARED-BOUNDARY PRODUCT REPAIR
Product source remains unchanged at a4209d005ea0a1476f8eafb4822f4d39ac50ee5a. QA terminal head bc72a86e16a55331a71d8d749d09870c1f018c6b remains evidence-only with no exact-head Actions, therefore INCONCLUSIVE rather than GREEN.

A coherent Product repair with deterministic regressions and observable exact-head CI must close/reconcile all twelve locked classes:
1. reject import/ChessBase symlink/reparse indirection;
2. enforce bounded PGN reads and finite source-size limits;
3. prevent serialized local-path leakage;
4. close expected_sha256 commit-boundary TOCTOU;
5. make overwrite=False safe against competing creators;
6. reject PGN export filesystem-indirection/symlink escape;
7. distinguish companion-directory I/O failure from ordinary no-companion evidence;
8. make ImportRegistry.inspect_batch record importer RuntimeError and continue later inputs;
9. convert manifest hash/open OSError/PermissionError into explicit failed verification;
10. reject FIFO/device-like/non-regular inputs before any ordinary fingerprint open;
11. make provenance hashing stable against concurrent same-size mutation on BOTH shared import_contract.fingerprint() and ChessBase integrity fingerprint paths;
12. redact/safely classify failed ACSDB import diagnostics before persistence/application exposure so private paths, token-like provider detail and raw exception internals do not cross import-history reporting boundaries.

Do not weaken QA gates. Preserve useful error classification without leaking raw private detail. Do not take Windows strict/release ownership.

## DEV5 — DIRECTIVE 0019
Take a fresh cutoff first. If any touching DEV1/DEV3/DEV4/DEV5 worker is IN_PROGRESS before cutoff, use SAFE OVERLAP only: CI/evidence review, conflict preparation, backlog ordering and directives; no competing Product push.

If touching lanes are terminal before cutoff, perform one selective validation composition:
1. add cumulative DEV1 WebView + Teacher WebView Product/tests through b873e18... in dependency order, excluding workflow metadata;
2. fresh-evaluate DEV3 lineage and add only terminal dependency-correct non-PGN Product/tests (including StudentProgressStore and search resource bounds only if their current canonical state is terminal at that cutoff);
3. preserve canonical DEV2 GameTree/domain authority and one existing engine/analysis authority;
4. run combined DEV1 Teacher/WebView + canonical GameTree + DEV3 ACSDB/Search/Books/Training/Student focused regressions, full unittest, full pytest and complete diagnostic on one exact validation SHA;
5. keep shared PGN/ChessBase/import promotion blocked until DEV4 terminal Product repair exists for all twelve classes with exact observable CI;
6. after repair, selectively layer only accepted shared-boundary fixes and run PGN -> canonical GameTree -> ACSDB -> Search/Open vertical covering malformed-input atomicity, bounded resources, no lost updates, batch continuation, path/error privacy, provenance stability, retry/recovery, special-file rejection, SQLite bounds and keyboard/focus invariants.

Persistent full5 authority may advance only as far as exact-SHA GREEN evidence proves. Evidence PRs stay DO NOT MERGE wholesale. Fresh Windows candidate requires the complete machine release chain on the exact final audited Product SHA. NVDA_VERIFIED remains NO until the user personally verifies that exact candidate.
