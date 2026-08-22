# DEV5_RUN_STATE

RUN_ID: 20260822-1341
STARTED_LOCAL: 13:41 Europe/Kyiv
STATUS: COMPLETE
MODE: SAFE_OVERLAP_COORDINATION
COORDINATION_BRANCH: manual5/dev5-regression-integration-20260821
STAGE1_INTEGRATION_TARGET: manual5/integration-20260821
STAGE1_INTEGRATION_SHA: 0fa442330bc2bb03636ff9297512da4c29e38684
SNAPSHOT_CUTOFF: 2026-08-22T13:41:44+03:00
DIRECTIVE_SNAPSHOT: NEXT_WAVE_DIRECTIVES 0014 effective 13:00; 0015 observed but future-effective at 14:00 and deliberately not overwritten
SNAPSHOT_POLICY: live GitHub branch/SHA/CI/logs are technical truth over stale Drive prose; do not infer terminal state from age alone
NVDA_VERIFIED: NO
FRESH_WINDOWS_CANDIDATE: NO
STAGE_2: BLOCKED

## Stage1 exact state
manual5/integration-20260821 remains exact 0fa442330bc2bb03636ff9297512da4c29e38684. Exact observable gates remain GREEN: Stage1 Saturation Hardening CI run 32532577641 SUCCESS and UI Semantic Gate run 32532577650 SUCCESS; the immediately prior pair 32532503262 / 32532503184 is also SUCCESS. No Stage1 Product mutation in this run. PR #54/frozen refs untouched; rejected ZIP not reused; no Windows candidate.

## DEV1 touching-lane snapshot
Canonical Drive DEV1_RUN_STATE RUN_ID 20260822-0041 still says STATUS=IN_PROGRESS on full5/dev1-accessible-shell-20260822 and has not been terminalized. PR #68 remains OPEN/DRAFT at c1425c898b3b6d1a4caea6a57a71544ee8582909. Exact changed-path inventory is presentation-only: acs/full_product_ui_shell.py, acs/teacher_presentation.py, tests/test_dev1_full_product_accessible_shell.py. No pull-request workflow runs are observable for exact c1425c... . Staleness is not permission to assume completion. SAFE OVERLAP therefore remains mandatory and DEV5 performs no competing full-product Product push.

## DEV2 terminal exact package
DEV2_RUN_STATE 20260822-1238 is COMPLETE. Canonical Product head: 4dd706838881c0e328c7578eada17227de43cf60. Validation-only PR #83 head 7822926f82354d86f03592c40fcafb2faf9342df; exact DEV2 Full Product Core CI run 32565884179 / job 97014330560 SUCCESS. Snapshot 21/21, navigation 8/8, editing 8/8, insertion 6/6, annotations 8/8, legality 6/6, result/exchange 8/8, GameTree 14/14, export 7/7 PASS; unittest 742 OK + 1 SKIP; pytest 822 PASS + 1 SKIP + 1330 subtests. FULL_PRODUCT_DEV2_READY_FOR_INTEGRATION=YES. PR #83 remains evidence-only / DO NOT MERGE.

Selective-lineage proof: comparing reusable Work head 6fa705f7ca80ee69b4183f99c9bc1c5a86048e64 to DEV2 4dd706838... gives merge-base 0cf4fe291ff6c349de99978cd2fc68866a218da8. The meaningful post-Work DEV2 delta is confined to GameTree/BookDocument domain modules and their tests plus the DEV2-only workflow: gametree_annotations/editing/insertion/legality/navigation/result_contract/snapshot, bookdocument and focused tests. It does not require taking cumulative ACSDB/PGN/Search/Training history from PR #69. Future assembly must consume this selective package, not the whole PR history.

## DEV3 exact technical package
Live PR #65 remains OPEN/DRAFT. Exact executable Product checkpoint remains 3dde3a7444c9cf594e92e32f5e084c8969015ad4. Current PR #65 head 23aba247aa47bc2f7aa7051798e1b9c1b84a3621 is eight commits ahead of 3dde3a... and those changes are docs/codex state files only; Product state has not moved. Validation PR #84 was CLOSED UNMERGED as intended. Exact evidence remains DEV3 Full Product ACSDB CI run 32563847332 / job 97009443566 SUCCESS on synthetic merge ref f1134af309c3fe687b039f2aea5c0068b353408c; focused 87/87, unittest 616/616, pytest 694 + 585 subtests, SELFTEST and complete WebView2 diagnostic PASS.

Lineage warning: DEV3 Product checkpoint 3dde3a... diverges from 6fa705... with merge-base e8cd992d306975955784118364ce950963133d7e. Therefore the DEV3 branch MUST NOT be merged wholesale into a modern shared/full-product base. Future DEV5 intake must selectively port and revalidate DEV3-owned ACSDB/Library/Search/recovery/query-plan, PGN publication, Books/Training persistence and signed-64-bit search-scalar semantics while preserving newer canonical DEV2 GameTree and accepted Stage1/UI semantics.

## DEV4 13:00 independent QA
DEV4_RUN_STATE 20260822-1300-full-product-qa is COMPLETE / SAFE_OVERLAP_QA_EVIDENCE. QA branch exact head 5d43b944b3fce7a798f2d002d691591ff9702fcd; PR #67 OPEN/DRAFT/MERGEABLE. Exact-head Actions remain NONE OBSERVED => INCONCLUSIVE, NOT GREEN. Product code is unchanged by DEV4 QA.

Ten locked PROVEN_PRODUCT_DEFECTS now govern PGN/ChessBase/import readiness:
1. Import/ChessBase symlink-reparse indirection follows targets instead of failing closed.
2. PGN import lacks bounded full-text/resource handling and finite source cap.
3. Serialized ChessBase evidence leaks absolute local paths.
4. PGN expected_sha256 optimistic overwrite has TOCTOU lost-update race.
5. PGN overwrite=False can clobber a destination created after preflight.
6. PGN export filesystem indirection/symlink escape is not fail-closed.
7. ChessBase companion-directory I/O failure collapses into ordinary no-companion evidence.
8. ImportRegistry.inspect_batch aborts on importer RuntimeError instead of recording failure and continuing.
9. ChessBase verify_manifest_unchanged propagates hash/open I/O exceptions instead of explicit failed-verification evidence.
10. Shared import fingerprinting can open FIFO/device-like special files before validating regular-file status.

## Cross-plane lineage / rewrite-risk assessment
Reusable full-product Work head 6fa705... and accepted Stage1 0fa44233... diverge at e8cd992d...; neither is a safe whole-branch replacement for the other. Future persistent full5 integration therefore requires explicit selective reconciliation: accepted Stage1 semantics + terminal DEV1 presentation delta + clean DEV2 GameTree delta + selected exact DEV3 data/backend delta + only repaired DEV4 PGN/ChessBase behavior. Evidence PRs remain non-authoritative and must not be wholesale merged.

## Product action this run
NONE. SAFE OVERLAP only. No full5 integration branch created or advanced, no Product cherry-pick/merge/push, no Windows strict changes. This run performs fresh live inspection, exact CI verification, lineage/conflict analysis and durable coordinator synchronization.

## Readiness matrix (integration-readiness estimates, not release acceptance)
Stage1 machine integration: high / exact current gates GREEN; last independent overall estimate remains about 93%, still blocked by fresh Windows release chain and human NVDA.
GameTree/domain full-product backend: ~70-75% isolated/validated; not yet in persistent full5 integration.
ACSDB/Library/Search backend: ~65-70% isolated/validated; selective integration still pending.
Full-product UI/accessibility shell + Teacher presentation: ~20-25%; DEV1 foundation exists but remains non-terminal.
PGN/ChessBase import-export: ~25-30%; ten proven security/concurrency/resource defects remain.
Books/Training persistence: ~30-35%; backend contracts exist, end-to-end accessible vertical slices not assembled.
Teacher/Classroom/Classes/Lessons/Assignments/Remote: ~10% integrated readiness; no complete persistent end-user vertical slice yet.
Overall full-product integrated end-user readiness: ~20-25%; deliberately conservative because persistent full5 integration and cross-subsystem vertical CI do not yet exist.

## Next three highest-value actions
1. DEV1 terminalize exact UI/accessibility/Teacher foundation package with canonical RUN_STATE/handoff and observable evidence.
2. Product owner(s) repair DEV4 ten PGN/ChessBase/import defects with strict regressions; no test weakening.
3. After SAFE OVERLAP clears, DEV5 builds validation-only composition from accepted Stage1 + terminal DEV1 + selective DEV2 4dd706... + selective DEV3 3dde3a..., then runs PGN -> canonical GameTree -> ACSDB -> search/open cross-lane failure/accessibility matrix before any persistent full5 integration ref moves.

## Release boundary
READY_FOR_RELEASE=NO. No fresh Windows candidate. NVDA_VERIFIED=NO until Oleksii personally verifies the exact machine-gated candidate.
