# DEV4 RUN STATE

RUN_ID: 20260821-2335-full-product-qa
STATUS: COMPLETE
MODE: SAFE_OVERLAP_QA_EVIDENCE
ROLE: DEV4 independent QA/evidence/security

## Live snapshot

- DEV4 Product branch: `manual5/dev4-platform-security-packaging-20260821`
- DEV4 Product head observed: `a4209d005ea0a1476f8eafb4822f4d39ac50ee5a`
- Manual5 integration branch: `manual5/integration-20260821`
- Integration head observed: `e24ff85ff9a6ad3ea19d33f7035526c7bcdf2c8e`
- QA branch: `qa/dev4-chessbase-symlink-security-20260822`
- QA evidence head before this state commit: `275b54669df4664d05775e92165c7c7f7397ee93`
- QA draft PR: #67 `QA DEV4: ChessBase symlink security gate`
- DEV5 active reconciliation: draft PR #66, head `09156cbca6bba0b6ba833cf3c867b127345014cf`; settings-boundary slice only.

## Directive

Drive `04_DEV4_PLATFORM_SECURITY_PACKAGING_TASK.txt` is now Full Product and effective immediately. DEV4 owns ChessBase/import-export/provenance/security/package/migration-safety evidence. Stage1 reconciliation remains DEV5/Audit-authorized only. Core/GameTree remains DEV2; ACSDB query/storage performance remains DEV3; Windows UX remains DEV1; integration remains DEV5.

## Findings

### PROVEN_PRODUCT_DEFECT — external import symlink/reparse fail-closed boundary

Current `acs.import_contract.fingerprint()` opens symlink targets and serializes `Path.resolve()` as source provenance. `ImportRegistry._same_source()` also compares resolved paths. Current ChessBase `capture_integrity_snapshot()` and `build_chessbase_manifest()` accept symlink primary/component inputs because `Path.is_file()` follows symlinks; the manifest hashes the target and records its resolved path.

Independent filesystem reproduction confirmed `Path.is_file()` is true for a symlink to a regular file and `Path.resolve()` becomes the target. This violates the active Full Product DEV4 generic-import security contract requiring symlink/reparse inputs to fail closed and preserve the submitted source boundary.

QA regression evidence was added without Product changes in `tests/test_dev4_chessbase_symlink_security.py`:
1. generic fingerprint rejects symlink source;
2. ChessBase integrity snapshot rejects symlink primary;
3. ChessBase manifest does not follow/hash symlink primary;
4. ChessBase manifest does not hash symlink companion target.

Expected regression state on current Product code: RED. Do not weaken assertions to obtain GREEN.

### PROVEN_PRODUCT_INTEGRATION_RISK — Stage1 board bridge overlap

Preserve accepted integration/DEV1 `web/stage1_board_actions.js` semantics during DEV4 reconciliation. Do not wholesale overwrite it from terminal DEV4 Product tip.

### PROVEN_RELEASE_PIPELINE_BLOCKER — compiler report privacy

`nuitka-compilation-report.xml` must remain CI diagnostic evidence only and must not be embedded in a user candidate ZIP.

## CI/evidence status

- Existing integration exact-head Product gates at `e24ff85...`: UI Semantic Gate `32515103291` SUCCESS; Stage1 Saturation `32515103283` SUCCESS.
- QA head `275b546...`: commit-associated Actions currently UNOBSERVED. Do not infer GREEN or RED from absence of runs.
- No Windows candidate was created.
- `NVDA_VERIFIED=NO`.

## Boundary compliance

No force-push. No Product fix. No DEV5 reconciliation mutation. No integration mutation. No `tools/qa` or strict Windows workflow edits. No Windows strict WIP takeover. No Ctrl+A/Ctrl+C Product defect claim. No NVDA verification claim.
