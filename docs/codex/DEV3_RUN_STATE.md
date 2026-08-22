# DEV3 RUN STATE

RUN_ID: 20260822-2007-engine-move-resource-bounds-safe-overlap
STATUS: COMPLETE / TERMINAL
READY_FOR_INTEGRATION: YES
OVERALL_FULL_PRODUCT_DEV3: PARTIAL

BRANCH: auto/dev3-engine-move-resource-bounds-20260822
VALIDATION_PR: #130 (SAFE OVERLAP validation-only; do not merge whole PR)
PARENT_PRODUCT_HEAD: 6f5d19ead9d6b9176c64aaaf381a159c7c12fed8
VALIDATED_PRODUCT_HEAD: 654679e6f0ecba119b61aaeba9267a815bf8cd10
CI_BASE_HEAD: fb28b85035faf3b69fd682e1dc79e3cfe580a6fe
VALIDATION_MERGE_REF: 8222ba727ca8db79ba3a2c51521482d912299fdb

PACKAGE: existing earlier DEV3 engine-move resource-bound wave, validated in SAFE OVERLAP mode.
- normalized EngineMoveRequest FEN is capped at 512 characters before provider construction/use;
- custom engine movetime is capped at 60,000 ms;
- EngineMoveResult cannot claim movetime outside 50..60,000 ms;
- existing low custom movetime minimum clamp to 50 ms remains unchanged;
- no second chess/application state model or chess-legality parser was introduced.

EXACT CI EVIDENCE:
Workflow: DEV3 Engine Move Resource Bounds CI
Run: 32595776186
Job: 97086347001
Conclusion: SUCCESS
Focused engine/direct-analysis/assisted/continuous boundaries: 67/67 PASS
Full unittest: 708/708 PASS
Full pytest: 786 passed + 641 subtests PASS
SELFTEST: PASS
ACCESSIBLE CHESS 0.4 WEBVIEW2 COMPLETE USER FLOW DIAGNOSTIC: PASS
Diff hygiene: PASS
Compile: PASS
TEST_WEAKENING: NONE

SAFE OVERLAP: hidden earlier DEV3 ownership was discovered after competing PRs #128/#129 were opened. Both were closed unmerged. Their RED run 32595657079 / job 97086034134 is retained as truthful compatibility evidence; no competing Product line remains active.

FOLLOW_UP: EngineGameHandoff(ANALYZE_CURRENT_GAME) still needs the same 512-character FEN bound in a later non-overlapping package while preserving the stable `requires fen` error contract.

OWNERSHIP: DEV1 UI/WebView; DEV2 canonical GameTree/domain; DEV4 PGN/ChessBase/import security and active shared ACSDB repair; DEV5 integration/promotion. DEV3 did not mutate those lanes.
FRESH_WINDOWS_CANDIDATE: NO
NVDA_VERIFIED: NO
