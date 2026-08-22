# DEV3 RUN STATE

RUN_ID: 20260822-1902-analysis-request-bounds
STATUS: COMPLETE / TERMINAL
READY_FOR_INTEGRATION: YES
OVERALL_FULL_PRODUCT_DEV3: PARTIAL

BRANCH: auto/dev3-analysis-request-bounds-20260822
PRODUCT_PR: #101 (open/draft/evidence-only)
VALIDATION_PR: #102 (validation-only; do not merge into Product history)
BASE_TERMINAL_HEAD: 878396533a1b5d78c452202a6ecbbe764421e9ac
PRODUCT_CODE_COMMIT: 887e033db427837ed383a0f0ccbc1680aaa8ad63
TEST_COMMIT: f6103032fd9b0a7cb8c7a7f34404a656146e8b1c
VALIDATED_PRODUCT_CI_HEAD: 31647b904f6cbd112a8425db4017566e716d15e6
VALIDATION_MARKER_HEAD: ce0d7959cd89ba3ac7471ca7f676da7ca29fb405
VALIDATION_MERGE_REF: e2d42745d216baaf507ee84ef2b49fc4adf16383

PACKAGE: direct AnalysisService FEN request resource bounds.
- normalized FEN length is capped at 512 characters before generation publication, provider construction, or UCI work;
- invalidate() uses the same bounded request contract;
- AnalysisResult fails closed on oversized FEN output;
- existing multipv/depth clamp, stale-generation semantics, engine serialization/ownership, GameReview behavior, and canonical state ownership are unchanged.

EXACT CI EVIDENCE:
Workflow: DEV3 Full Product ACSDB CI
Run: 32583809015
Job: 97057031894
Conclusion: SUCCESS
Focused DEV3 suite: 173/173 PASS
Official Stockfish 18 bounded game-review smoke: PASS
Stockfish archive SHA-256: 536c0c2c0cf06450df0bfb5e876ef0d3119950703a8f143627f990c7b5417964 VERIFIED
Full unittest: 689/689 PASS
Full pytest: 767 passed + 641 subtests PASS
SELFTEST: PASS
ACCESSIBLE CHESS 0.4 WEBVIEW2 COMPLETE USER FLOW DIAGNOSTIC: PASS
Diff hygiene: PASS
Compile: PASS
TEST_WEAKENING: NONE

OWNERSHIP: DEV1 UI; DEV2 canonical GameTree/domain; DEV4 PGN/ChessBase/import security; DEV5 integration/promotion. DEV3 did not mutate those lanes.
KNOWN_BLOCKER: mistake/blunder classification still awaits terminal authoritative student/actor plus fixed evaluation-perspective contract; no parallel domain model will be created.
FRESH_WINDOWS_CANDIDATE: NO
NVDA_VERIFIED: NO
