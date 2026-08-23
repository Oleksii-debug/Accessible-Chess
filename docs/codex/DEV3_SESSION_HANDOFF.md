# DEV3 SESSION HANDOFF

DEV3 continuation remains SAFE OVERLAP / release-support. No Product or QA-harness mutation was made because the active Stage1 privacy repair is owned by DEV5 and the Windows candidate/release chain remains downstream.

Accepted Stage1 Product authority: `manual5/integration-20260821 @ 0fa442330bc2bb03636ff9297512da4c29e38684`.

DEV3 exact Windows runtime evidence remains GREEN in PR #142: `DEV3 Stage1 Runtime Evidence / 32600115025 / 97097006614`, with 177/177 focused Stockfish/analysis/clocks/lifecycle PASS, official Stockfish 18 real runtime, one shared provider, MultiPV=5 restoration, packaged relative Stockfish path, SELFTEST and complete WebView2 diagnostic PASS.

NEW EXACT DEV3 EVIDENCE: PR #150 (`qa/dev3-stage1-engine-start-privacy-evidence-20260823 @ 94fc9a8a1f708da66319d9ea63718376d339bc10`) ran `DEV3 Stage1 Engine Start Path Privacy Evidence / 32627037392 / 97163830449`. Exact accepted-source lock, evidence-only diff and compile PASS; existing UCI recovery 3/3 PASS; privacy oracle 2/2 FAIL. Accepted Stage1 republishes private Stockfish executable paths in both OSError/FileNotFoundError and ValueError startup failures. This establishes `PROVEN_STAGE1_ENGINE_START_PRIVACY_DEFECT=YES` without establishing a broader Stockfish runtime defect.

Earlier PR #148 remains exact evidence that accepted Stage1 also leaks private parent paths from PGN existing-destination and ImportRegistry provenance diagnostics (`32624495674 / 97157620475`). Current accepted source is therefore release-blocked on multiple path-privacy surfaces until a repaired SHA is explicitly promoted.

ACTIVE REPAIR OWNER: DEV5 PR #151, current head `f99146f728ace6f76606beeea6caafbb6ac940e9`.
- Initial run `32627055689` was inconclusive because the Product-owned privacy fixture attempted the same mkdir twice with `exist_ok=False`; DEV3 classified it in comment `5384960853`.
- Corrected rerun `32627159257`: Linux job `97164119089` SUCCESS through Product privacy tests, independent QA privacy oracles unchanged, full unittest, full pytest and complete diagnostic. Windows job `97164119275` has privacy regressions 6/6 PASS, then 74/75 focused Stage1 release tests PASS. The only failure is frozen-core working-tree blob identity for `stage1_release_ui_core.py`: observed `d926aa21cbf966b193f1249d2fb811beb9c49403` vs frozen LF blob `b8586a26b9ab20c3d3ec0b0a3dbbbd53e38e94e6`. PR #151 does not modify that core file; workflow configures LF only after checkout, so checkout-time CRLF materialization is the current CI blocker. DEV3 recorded exact CI-only remediation direction in comment `5384964048` without weakening assertions.

NEXT DEV3 ACTION: fresh ownership read, then inspect the next PR #151 exact-head rerun after LF rematerialization. If Linux + Windows complete validation is GREEN and Audit promotes a repaired Stage1 SHA, replay DEV3 privacy oracles unchanged against that exact authority. Only then follow the fresh Windows candidate through strict UIA, packaged Stockfish/sound, release preflight, ZIP identity and artifact upload. Open DEV3 Product code only for a newly proven runtime/analysis/clock/lifecycle defect.

SAFE_OVERLAP=YES
PROVEN_STAGE1_RELEASE_PRIVACY_DEFECT=YES
PROVEN_STAGE1_ENGINE_START_PRIVACY_DEFECT=YES
DEV3_PRODUCT_PATCH_REQUIRED=NO
FRESH_WINDOWS_CANDIDATE=NO
NVDA_VERIFIED=NO
