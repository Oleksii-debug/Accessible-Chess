# Cross-repository desktop update reuse — 2026-10-05

Status: implementation branch `work/desktop-update-crossrepo-reuse-20261005`.

## Purpose

Reuse already-developed first-party update verification instead of asking users to manually replace installations forever or inventing a new updater from scratch.

This pass deliberately implements **verification only**. It does not download, execute, unpack, replace the running EXE, or claim update authenticity from a hash alone.

## Donor research

### scripture-archive — selected donor

Branch:
`qa-current-package-accessibility-0913-sol`

Donor:
`runtime_engine/scripture_archive_runtime/application_update.py`
blob:
`4d621a3013df7f50984906fcdb59ffe6b6ae98f7`

Adapted destination:
`acs/application_update.py`

Reusable guarantees retained:
- strict SemVer parsing/comparison;
- exact manifest shape;
- duplicate JSON-key rejection;
- non-finite JSON rejection;
- product and platform binding;
- exact 40-hex source commit identity;
- bounded artifact size;
- exact SHA-256 binding;
- portable/Windows-safe artifact file names;
- Windows reserved-device-name rejection;
- local artifact must be a regular non-symlink file;
- metadata before/after hashing must match, detecting replacement/growth during verification;
- default downgrade rejection.

Accessible Chess authority changes:
- schema: `accessible-chess.application-update.v1`;
- product id: `accessible-chess`;
- platform: `windows-x64`;
- package limit raised to 4 GiB to cover the real Windows distribution envelope.

### AutoTrade — researched but not copied wholesale

Donor:
`mvp/autotrade_mvp/windows_update.py`
blob:
`03ceb7d61f12dd0770cb214929c9f44a4cbf9fdb`

Its update planner is stronger for signed qualification/backup/migration evidence, but it depends on AutoTrade-specific financial release authorities, artifact stores, reconciliation, journal schema, and signed qualification types. Copying it would create unrelated authorities and dependencies inside Accessible Chess.

Useful design retained for future work:
- install execution must be separate from verification;
- pre-update backup evidence must be qualified;
- update and rollback must be explicit plans;
- the candidate must be bound to exact signed release evidence before automatic installation.

## Current boundary

`acs/application_update.py` proves only:

> the locally supplied artifact exactly matches a manifest for this product/platform/version/source identity.

It does **not** prove:
- publisher identity;
- Authenticode signature trust;
- server/source authenticity;
- entitlement;
- safe automatic replacement;
- rollback readiness.

Those must be added before commercial automatic-update execution is enabled.

## Qualification

`tests/test_application_update_crossrepo.py` covers:
- SemVer precedence;
- byte verification;
- hash mismatch;
- product/platform mismatch;
- equal-version/downgrade rejection;
- duplicate-key/non-finite manifest rejection;
- Windows reserved file names;
- local file exact-name and hash verification;
- symlink rejection where supported.

The dedicated CI workflow runs on Windows and Ubuntu.
