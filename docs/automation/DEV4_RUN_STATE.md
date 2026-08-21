# DEV4 RUN STATE

RUN_ID: 20260822-0205-full-product-qa
STATUS: COMPLETE
MODE: SAFE_OVERLAP_QA_EVIDENCE
ROLE: DEV4 independent QA/evidence/security

## Live snapshot

- DEV4 Stage1 Product source: `manual5/dev4-platform-security-packaging-20260821` @ `a4209d005ea0a1476f8eafb4822f4d39ac50ee5a`.
- Manual5 integration: `manual5/integration-20260821` @ `0fa442330bc2bb03636ff9297512da4c29e38684`.
- Exact integration CI: UI Semantic Gate `32532577650` SUCCESS; Stage1 Saturation `32532577641` SUCCESS.
- DEV5 active/recent reconciliation draft PR #66: `manual5/dev5-reconcile-dev4-20260822` @ `abff45ebcc4b5af2a85ab0c456b025b5098c6e29`.
- Exact DEV5 reconciliation CI: UI Semantic Gate `32532415239` SUCCESS; Stage1 Saturation `32532415296` SUCCESS.
- DEV4 QA branch: `qa/dev4-chessbase-symlink-security-20260822` @ `e456a9cc3613192fd67a427e383c1ccb72cb1241`.
- DEV4 QA draft PR: #67, title `QA DEV4: import symlink + PGN resource + report privacy gates`.
- Exact QA-head commit-associated Actions: none observed. Classification: INCONCLUSIVE CI observability, not GREEN.
- Requested `AGENTS.md` and `docs/codex/{CURRENT_STATE,NEXT_WORK,SESSION_HANDOFF}.md` remain absent on checked live refs. Active Drive directive plus `docs/automation/DEV4_*`, GitHub and canonical Drive handoff are controlling state.
- Windows strict WIP=1 remains untouched. `NVDA_VERIFIED=NO`.

## Active directive

Drive `04_DEV4_PLATFORM_SECURITY_PACKAGING_TASK.txt` is Full Product 5.5x and assigns DEV4 ChessBase/import-export/provenance/security/package/migration-safety evidence. Integration remains DEV5, Core/GameTree DEV2, ACSDB query/storage performance DEV3, Windows UX DEV1. No QA strict harness ownership transfer occurred.

## Findings

### PROVEN_PRODUCT_DEFECT — external import symlink/reparse fail-closed boundary

Shared import/ChessBase provenance still follows filesystem indirection instead of rejecting it. `fingerprint()` and ChessBase integrity/manifest paths can hash target bytes and normalize away the submitted symlink boundary. Strict QA gate remains `tests/test_dev4_chessbase_symlink_security.py`.

### PROVEN_PRODUCT_DEFECT — PGN unbounded read/resource-exhaustion boundary

`acs.pgn_service._read_text_snapshot()` fingerprints in bounded chunks and then reads the complete untrusted PGN with unbounded `handle.read()`, without explicit maximum source size or streaming parser boundary. Strict QA gate remains `tests/test_dev4_pgn_resource_security.py`.

### PROVEN_PRODUCT_DEFECT — private local paths serialized into ChessBase report/provenance DTOs

Direct live source proves absolute/local paths are emitted by:
- `ChessBaseSourceProbe.as_report_fields()` / `ChessBaseComponent.as_report_fields()`;
- `ChessBaseIntegritySnapshot.as_report_fields()` / `SourceFileEvidence.as_report_fields()`;
- `ChessBaseBundleManifest.as_dict()` / `ComponentEvidence.path`.

This contradicts the active Full Product export/report requirement for no secret/local path leakage. QA-only strict gate `tests/test_dev4_chessbase_report_path_privacy.py` now covers probe, integrity snapshot and manifest serialization. It does not prescribe the replacement representation; it only forbids exposing the private absolute path.

### Evidence artifact — ChessBase capability matrix

`docs/automation/DEV4_CHESSBASE_CAPABILITY_MATRIX.md` now records evidence-backed current states for CBH, CBG, CBP, CBT, CBV, CBF, 2CBH and CBONE. Recognition/provenance is explicitly separated from proprietary decoder support; no lossless/decode claim is inferred from suffix recognition.

### Preserved findings

- PROVEN_PRODUCT_INTEGRATION_RISK: preserve accepted DEV1/integration `web/stage1_board_actions.js` semantics during any Stage1 reconciliation.
- PROVEN_RELEASE_PIPELINE_BLOCKER: `nuitka-compilation-report.xml` may be CI diagnostic evidence only and must not ship in a user ZIP.
- HUMAN_ONLY: exact fresh Windows native-menu/NVDA usability. `NVDA_VERIFIED=NO`.
- No Product Ctrl+A/Ctrl+C defect is claimed.

## QA commits this run

- `7285a33f241cc6ebf9cdec4cf7bf9ee24095d603` — `test(security): gate ChessBase report path leakage`.
- `ef6195bae93baa1e629564ba43c08e4ee41cc9a0` — `test(security): extend ChessBase report privacy gate`.
- `e456a9cc3613192fd67a427e383c1ccb72cb1241` — `docs(qa): add ChessBase capability matrix`.

No Product source fix is included. No security assertion was weakened to manufacture GREEN.

## Evidence discipline / boundaries

No force-push. No DEV5/integration mutation. No `tools/qa` or strict Windows workflow edit. No DEV3 ACSDB performance takeover. No frozen release merge. No Windows candidate. Exact QA PR Actions are unobserved and remain INCONCLUSIVE rather than inferred GREEN. Existing integration/DEV5 GREEN does not cover the new external-format QA assertions.

## Next action

1. Recheck PR #67 exact-head Actions without reclassifying absence as GREEN.
2. Audit PGN export safety: destination/path policy, directory/symlink boundary, overwrite/concurrency semantics, temporary-file permissions/cleanup and atomic replacement failure behavior.
3. Continue generic import resource audit: explicit maximum source sizes, truncation, encoding abuse, duplicate-source behavior and cancellation/recovery.
4. Trace generic `SourceFingerprint.path`, `BatchInspectionItem.error` and PGN exceptions into actual persisted/UI/report surfaces; classify only when the boundary is proven.
5. Audit ChessBase unknown-version/resource limits beyond bounded hashing; do not invent proprietary decoder semantics.
6. Re-enter Stage1 package work only through DEV5/Audit-authorized reconciliation and verify future user ZIP excludes `nuitka-compilation-report.xml`.
