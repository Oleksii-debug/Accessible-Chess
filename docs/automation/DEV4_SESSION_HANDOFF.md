# DEV4 SESSION HANDOFF

SESSION: 20260821-2335 Full Product QA/security
STATUS: COMPLETE / SAFE OVERLAP

## Exact branches and SHAs

- Product source: `manual5/dev4-platform-security-packaging-20260821` @ `a4209d005ea0a1476f8eafb4822f4d39ac50ee5a`
- Accepted manual5 integration observed: `manual5/integration-20260821` @ `e24ff85ff9a6ad3ea19d33f7035526c7bcdf2c8e`
- DEV5 active reconciliation observed: `manual5/dev5-reconcile-dev4-20260822` @ `09156cbca6bba0b6ba833cf3c867b127345014cf`, draft PR #66
- DEV4 QA evidence branch: `qa/dev4-chessbase-symlink-security-20260822`
- Regression implementation commits: `d4e10e94a0f4d1ffb11e1d6190fb3c84e039d432`, `275b54669df4664d05775e92165c7c7f7397ee93`
- QA draft PR: #67

## What changed

Only QA regression/evidence and QA automation notes were added. No Product source changed.

The regression gate proves the active external-import security contract must reject symlink/reparse-style indirection rather than hashing/normalizing the target. Current generic fingerprint, ChessBase integrity snapshot and ChessBase manifest paths do not satisfy that contract.

## Finding ledger

- `PROVEN_PRODUCT_DEFECT`: generic/ChessBase import provenance follows symlinks and can hash the target while losing the submitted indirection boundary.
- `PROVEN_PRODUCT_INTEGRATION_RISK`: naive DEV4 `stage1_board_actions.js` overwrite would regress accepted DEV1/integration semantics.
- `PROVEN_RELEASE_PIPELINE_BLOCKER`: Nuitka compiler report must not ship in user ZIP.
- `QA_OR_ENVIRONMENT_ONLY`: none newly proven this session.
- `INCONCLUSIVE`: QA PR #67 CI because no commit-associated run was observable at last check.
- `HUMAN_ONLY`: exact fresh Windows native-menu/NVDA usability; `NVDA_VERIFIED=NO`.

## Existing exact integration evidence

At `e24ff85ff9a6ad3ea19d33f7035526c7bcdf2c8e`:
- UI Semantic Gate run `32515103291`: SUCCESS.
- Stage1 Saturation Hardening run `32515103283`: SUCCESS.

These do not validate the new QA symlink assertions because DEV4 Full Product import-security work is outside that already-green accepted Stage1 snapshot.

## Coordination

DEV5 owns reconciliation/integration and is actively validating settings-boundary DEV4 slice in PR #66. DEV4 must not mutate that branch or duplicate the settings work. DEV3 owns ACSDB storage/query performance and has active Full Product work; DEV4 should stay at adapter/provenance/migration-safety evidence boundaries.

## Next action

Continue read-only/QA audit of shared import/PGN provenance and ChessBase capability/security, recheck PR #67 CI, and hand the symlink defect to the appropriate Product intake without weakening the regression. Re-enter Stage1 reconciliation only when DEV5/Audit authorizes a slice.

No Windows candidate created. No strict Windows ownership taken. No Ctrl+A/Ctrl+C Product claim. `NVDA_VERIFIED=NO`.
