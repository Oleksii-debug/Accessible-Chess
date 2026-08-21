# DEV4 RUN STATE

RUN_ID: 20260822-0109-full-product-qa
STATUS: COMPLETE
MODE: SAFE_OVERLAP_QA_EVIDENCE
ROLE: DEV4 independent QA/evidence/security

## Live snapshot

- DEV4 Product branch: `manual5/dev4-platform-security-packaging-20260821`
- DEV4 Product head observed: `a4209d005ea0a1476f8eafb4822f4d39ac50ee5a`
- Manual5 integration branch observed: `manual5/integration-20260821` @ `e24ff85ff9a6ad3ea19d33f7035526c7bcdf2c8e`
- DEV5 active reconciliation: draft PR #66, `manual5/dev5-reconcile-dev4-20260822` @ `09156cbca6bba0b6ba833cf3c867b127345014cf`; settings-boundary slice only.
- DEV4 QA branch: `qa/dev4-chessbase-symlink-security-20260822`
- QA draft PR: #67
- New QA regression commit this run: `a2fb7961f1e740b20927224dff54d10d6a9d5376` — `test(security): gate unbounded PGN reads`.
- `AGENTS.md` and requested `docs/codex/{CURRENT_STATE,NEXT_WORK,SESSION_HANDOFF}.md` were not present on the live repository refs checked; active QA automation/handoff files and Drive directive were used instead.

## Directive

Drive `04_DEV4_PLATFORM_SECURITY_PACKAGING_TASK.txt` remains the active Full Product directive. DEV4 owns ChessBase/import-export/provenance/security/package/migration-safety evidence. Integration remains DEV5; Core/GameTree DEV2; ACSDB query/storage performance DEV3; Windows UX DEV1. Windows strict WIP=1 remains untouched.

## Findings

### PROVEN_PRODUCT_DEFECT — external import symlink/reparse fail-closed boundary

Unchanged from the prior run. `acs.import_contract.fingerprint()` follows symlinks and stores `Path.resolve()` provenance; `ImportRegistry._same_source()` normalizes both paths; ChessBase integrity/manifest paths accept file symlinks and can hash target bytes. Strict QA assertions remain in `tests/test_dev4_chessbase_symlink_security.py` and must stay RED until Product code genuinely fails closed.

### PROVEN_PRODUCT_DEFECT — unbounded PGN read / resource-exhaustion boundary

`acs.pgn_service._read_text_snapshot()` fingerprints the source in bounded chunks but then reads the entire untrusted PGN with `handle.read()` without a size/resource cap before parsing. This contradicts the active DEV4 contracts requiring bounded reads and fail-closed handling for huge/truncated external files/resource exhaustion.

QA-only regression added in `tests/test_dev4_pgn_resource_security.py`. It supplies a text handle that rejects `read()` calls without an explicit positive bound. Current Product code is expected to fail this regression because it calls `handle.read()` with the default unbounded size. No Product fix was made and the assertion was not weakened.

### INCONCLUSIVE — user-facing absolute-path leakage

Several internal PGN/import errors and provenance DTOs retain source/destination paths, and `ImportRegistry.inspect_batch()` stores `str(exc)`. Whether an absolute private path reaches a user-facing surface has not yet been traced end-to-end, so this remains a leakage risk, not a proven user-visible defect.

### Preserved findings

- `PROVEN_PRODUCT_INTEGRATION_RISK`: preserve accepted DEV1/integration `web/stage1_board_actions.js` semantics during any DEV4 Stage1 reconciliation.
- `PROVEN_RELEASE_PIPELINE_BLOCKER`: `nuitka-compilation-report.xml` may be CI evidence only; it must not ship in a user ZIP.
- `HUMAN_ONLY`: exact fresh Windows native-menu/NVDA usability. `NVDA_VERIFIED=NO`.

## CI/evidence status

- Accepted integration `e24ff85...`: UI Semantic Gate `32515103291` SUCCESS; Stage1 Saturation `32515103283` SUCCESS.
- QA PR #67 old head had no commit-associated Actions; new QA head must be rechecked after these evidence commits. Absence of Actions is `INCONCLUSIVE`, never GREEN.
- Local clone/test execution was unavailable in this environment because `github.com` DNS resolution failed; no local PASS/FAIL is claimed.
- No Windows candidate created.

## Boundary compliance

No force-push. No Product source fix. No DEV5 reconciliation or integration mutation. No DEV3 ACSDB performance takeover. No `tools/qa` or strict Windows workflow edits. Windows strict WIP=1 respected. No Ctrl+A/Ctrl+C Product defect claim. `NVDA_VERIFIED=NO`.
