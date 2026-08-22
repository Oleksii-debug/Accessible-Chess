# Accessible Chess autonomous next-wave directives

DIRECTIVE_VERSION: 0018
ISSUED_BY: DEV5 Coordinator/Integrator
EFFECTIVE_FROM_WAVE: 2026-08-22T16:00:00+03:00
PREVIOUS_DIRECTIVE: 0017 effective 15:00 Europe/Kyiv remains authoritative for workers that started under the 15:00 wave; never change an in-flight worker's snapshot semantics mid-run.
SNAPSHOT_SEMANTICS: Every worker must take a fresh cutoff at invocation start. Evidence or terminal handoffs created after that cutoff belong only to a later invocation. Never abandon recoverable in-flight work because a newer directive appears.

## GLOBAL BASELINE
Accepted Stage1 integration remains manual5/integration-20260821 @ 0fa442330bc2bb03636ff9297512da4c29e38684. PR #54/frozen refs remain protected. No Stage1 churn. Old rejected ZIPs remain forbidden.

DEV5 exact-GREEN full-product validation baseline remains full5/dev5-selective-compose-20260822 @ 7f4d2af3447d8d5046c9a75e1243a4ce36b11e4a, PR #88 OPEN/DRAFT/DO NOT MERGE. Exact DEV5 CI 32569504104 / 97022845834 SUCCESS: DEV1 78/78; canonical GameTree/BookDocument 22/22; unittest 718/718; pytest 796 + 791 subtests; SELFTEST and complete WebView2 diagnostic PASS.

The current accepted validation plane intentionally excludes shared PGN/external-import/ChessBase Product behavior while DEV4 defects remain unresolved.

## DEV1 — DIRECTIVE 0018
Eligible terminal incremental WebView accessibility package exists after the previously accepted DEV1 head.
Branch: full5/dev1-webview-composition-20260822-1439
Exact terminal head: 98ad9347d1a4e4a4c6bf766b93146f380675d471
Exact CI: 32571036182 SUCCESS.
Increment relative to accepted DEV1 995f7846... is exactly four commits and three paths:
- acs/full_product_webview_adapter.py
- tests/test_dev1_full_product_webview_adapter.py
- .github/workflows/dev1-full-product-ui-ci.yml
Focused 58/58, canonical accessibility/service 65/65, unittest 669/669, pytest 747 + 713 subtests, diagnostic PASS.
Do not churn these paths unless a concrete combined-validation defect appears. DEV5 may selectively intake the Product/test delta on a later no-overlap cutoff; do not merge PR #89 wholesale.

## DEV2 — DIRECTIVE 0018
No new DEV2 Product package is required. RUN_STATE 20260822-1441 is COMPLETE / WAITING_AUDIT. Canonical full-product head 4dd706838881c0e328c7578eada17227de43cf60 remains represented in DEV5 GREEN validation. Preserve canonical GameTree/BookDocument semantics, CommentStyle.SEMICOLON round-trip and accepted DEV1 keybinding/action contracts. Resume Product only for a concrete DEV2-owned P0/P1 or fresh Audit return.

## DEV3 — DIRECTIVE 0018
The 14:57 DEV5 wave observed a newer DEV3 terminal handoff only after that wave's cutoff, so it was quarantined rather than retroactively accepted. At the next invocation, take a fresh cutoff and verify whether DEV3 is terminal before using it.
Observed post-cutoff candidate for fresh re-evaluation:
- branch auto/dev3-acsdb-stable-paging-20260821
- coordination head 05024f51e325732bce0c10eae32981889757a2a5
- executable Product commit 047bdea014964395f95a115fb21cc96c167f3130
- exact CI 32571590992 / 97027694064 SUCCESS
- delta from already accepted DEV3 51d77c4... is three commits; Product additions are acs/engine_assisted_workflows.py and acs/student_progress.py with their dedicated tests; workflow/docs metadata are separate.
Do not consume this package if any touching DEV3 continuation is already IN_PROGRESS at the new cutoff. Never merge PR #65 wholesale. Preserve DEV1 presentation authority, DEV2 canonical GameTree, DEV4 shared PGN/import ownership and one existing AnalysisService/engine provider.

## DEV4 — DIRECTIVE 0018 — HIGHEST PRIORITY SHARED-BOUNDARY PRODUCT REPAIR
Eligible terminal QA before the 14:57 cutoff raised the locked count to twelve. Product source is still unchanged at a4209d005ea0a1476f8eafb4822f4d39ac50ee5a and no terminal Product repair exists. QA exact head c6b29e7beadbfbd0d49d22aafaaebaa7a412158a has no commit-associated Actions, so QA observability remains INCONCLUSIVE.

Produce a coherent Product repair package with deterministic regressions and observable exact-head CI that closes or explicitly reconciles all twelve:
1. reject import/ChessBase symlink/reparse indirection;
2. enforce bounded PGN reads and finite source-size limits;
3. prevent serialized local-path leakage;
4. close expected_sha256 commit-boundary TOCTOU;
5. make overwrite=False safe against competing creators;
6. reject PGN export filesystem-indirection/symlink escape;
7. distinguish companion-directory I/O failure from ordinary no-companion evidence;
8. make ImportRegistry.inspect_batch record importer RuntimeError and continue later inputs;
9. convert manifest hash/open OSError/PermissionError into explicit failed verification;
10. validate regular-file type before fingerprinting so FIFO/device-like inputs are never opened as ordinary imports;
11. make SourceFingerprint stable against concurrent same-size mutation during hashing, rejecting mixed/stale snapshots;
12. redact or safely classify failed ACSDB import diagnostics before persistence/application exposure so workstation paths, token-like provider details and raw private exception internals cannot cross the import-history boundary.

Do not weaken strict QA gates. Preserve useful failure classification/evidence without persisting raw secrets/private paths. Preserve DEV2 canonical GameTree, selected DEV3 publication semantics, DEV1 UI/action boundaries and Windows strict/release-owner isolation. No exact-head CI means INCONCLUSIVE, never GREEN.

## DEV5 — DIRECTIVE 0018
Take a fresh cutoff first.
If DEV3, DEV4, another DEV5 wave, or any touching owner is IN_PROGRESS before cutoff, enter SAFE OVERLAP: no competing Product push. Perform only CI/evidence review, conflict analysis, backlog ordering, selective-delta preparation and directives.

If all touching candidates are terminal before cutoff, selective validation order is:
1. overlay DEV1 incremental WebView Product/test delta after the already accepted DEV1 baseline; exclude lane workflow history unless needed only for evidence;
2. independently re-evaluate DEV3 post-cutoff candidate and selectively add only terminal dependency-correct Product/test additions from 51d77c4... -> 047bdea..., excluding docs/workflow metadata and any shared PGN/import path;
3. run combined presentation + canonical GameTree + ACSDB/Search/Books/Training/Teacher/Student regressions and full repository tests on an exact validation SHA;
4. keep PGN/ChessBase/import promotion blocked until terminal DEV4 Product repair for all twelve defects exists with exact observable CI;
5. after DEV4 repair, layer only accepted repaired shared boundaries and run dedicated PGN -> canonical GameTree -> ACSDB -> Search/Open vertical covering malformed-input atomicity, bounded resources, no lost updates, batch continuation, path/error privacy, provenance stability, retry/recovery, special-file rejection, signed-64-bit SQLite bounds, keyboard/focus invariants, full unittest, full pytest and complete diagnostic.

Persistent full5 authority must not advance beyond what exact-SHA GREEN evidence proves. Evidence PRs stay DO NOT MERGE wholesale. Fresh Windows candidate requires complete machine release chain on the exact final audited Product SHA. NVDA_VERIFIED remains NO until the user personally verifies that exact candidate.
