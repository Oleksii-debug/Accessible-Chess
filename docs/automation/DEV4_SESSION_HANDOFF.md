# DEV4 SESSION HANDOFF

SESSION: 20260822-0205 Full Product QA/security
STATUS: COMPLETE / SAFE OVERLAP

## Exact branches and SHAs

- DEV4 Stage1 Product source: `manual5/dev4-platform-security-packaging-20260821` @ `a4209d005ea0a1476f8eafb4822f4d39ac50ee5a`.
- Manual5 integration: `manual5/integration-20260821` @ `0fa442330bc2bb03636ff9297512da4c29e38684`.
- DEV5 reconciliation draft PR #66: `manual5/dev5-reconcile-dev4-20260822` @ `abff45ebcc4b5af2a85ab0c456b025b5098c6e29`.
- DEV4 QA evidence branch: `qa/dev4-chessbase-symlink-security-20260822`.
- QA branch head after this handoff sequence: `59a2126ee69b5adb91105ede7c6e393dad7aa7cd` or later sequential handoff commit; verify branch before intake.
- QA draft PR: #67.

## Live CI

Manual5 integration exact SHA `0fa442330bc2bb03636ff9297512da4c29e38684`:
- UI Semantic Gate `32532577650` — SUCCESS.
- Stage1 Saturation Hardening `32532577641` — SUCCESS.

DEV5 reconciliation exact SHA `abff45ebcc4b5af2a85ab0c456b025b5098c6e29`:
- UI Semantic Gate `32532415239` — SUCCESS.
- Stage1 Saturation Hardening `32532415296` — SUCCESS.

QA PR #67 exact pre-handoff evidence head `e456a9cc3613192fd67a427e383c1ccb72cb1241` had no commit-associated Actions. QA CI classification remains INCONCLUSIVE observability, not GREEN. Handoff-only commits do not convert this into Product evidence.

## Repository instruction discovery

`AGENTS.md` was not present on checked live refs. Requested `docs/codex/CURRENT_STATE.md`, `docs/codex/NEXT_WORK.md` and `docs/codex/SESSION_HANDOFF.md` were not found. Active Drive Full Product directive, live GitHub, `docs/automation/DEV4_*` and canonical Drive handoffs are the operative DEV4 sources.

## Findings

### PROVEN_PRODUCT_DEFECT — symlink/reparse import boundary

Generic import and ChessBase provenance/integrity/manifest paths follow filesystem indirection rather than failing closed. Strict QA coverage remains `tests/test_dev4_chessbase_symlink_security.py`.

### PROVEN_PRODUCT_DEFECT — PGN unbounded resource boundary

`acs.pgn_service._read_text_snapshot()` performs an unbounded full-text `handle.read()` after bounded hashing, with no explicit max source size or streaming parser boundary. Strict QA coverage remains `tests/test_dev4_pgn_resource_security.py`.

### PROVEN_PRODUCT_DEFECT — serialized ChessBase report path leakage

Direct live code serializes absolute/local source/component paths in probe report fields, integrity snapshot report fields and bundle manifest dictionaries. The active Full Product export/report contract forbids secret/local-path leakage. `tests/test_dev4_chessbase_report_path_privacy.py` now contains three strict cases covering probe, integrity and manifest serialization.

QA commits implementing this evidence:
- `7285a33f241cc6ebf9cdec4cf7bf9ee24095d603` — initial report privacy gate.
- `ef6195bae93baa1e629564ba43c08e4ee41cc9a0` — extend privacy gate to integrity and manifest payloads.
- `e456a9cc3613192fd67a427e383c1ccb72cb1241` — add evidence-backed ChessBase capability matrix.

No Product source fix is included and no assertion was weakened.

## ChessBase capability matrix

`docs/automation/DEV4_CHESSBASE_CAPABILITY_MATRIX.md` now classifies CBH/CBG/CBP/CBT/CBV/CBF/2CBH/CBONE using PARTIAL/BLOCKED states backed by current detection/provenance code. Recognition remains explicitly distinct from proprietary decoding; no lossless/decoder compatibility claim is made.

## Preserved findings / boundaries

- PROVEN_PRODUCT_INTEGRATION_RISK: preserve accepted DEV1/integration `web/stage1_board_actions.js` semantics.
- PROVEN_RELEASE_PIPELINE_BLOCKER: `nuitka-compilation-report.xml` must remain CI evidence only and stay out of user ZIPs.
- HUMAN_ONLY: exact fresh Windows native-menu/NVDA usability. `NVDA_VERIFIED=NO`.
- No Ctrl+A/Ctrl+C Product defect claim.
- Windows strict WIP=1 respected.
- No force-push, no DEV5/integration mutation, no `tools/qa` or strict Windows workflow edit, no DEV3 ACSDB performance takeover, no frozen release merge and no Windows candidate.

## Next action

Recheck the final QA branch head and PR #67 Actions; audit PGN export path/temp/overwrite/replace safety and generic import resource limits; trace generic provenance/error paths into actual persisted/UI/report surfaces; continue ChessBase unknown-version/resource-boundary evidence without inventing proprietary semantics; only re-enter Stage1 package work through DEV5/Audit-authorized reconciliation.
