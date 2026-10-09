# Section 51 — Owner profile transfer checkpoint

Status: **PARTIAL / NOT DONE**. This is a recovery and portability implementation,
not a release-ready NVDA workflow. Existing completed 51.1, 51.2 and 51.4
remain locked. User-accessible in-product picker/UI and verified packaged
Windows/NVDA acceptance remain to be completed.

## Implemented in this candidate

- `acs/user_data_transfer.py` reuses the canonical
  `Version2UpgradeCoordinator` backup scanner, SQLite snapshot, per-file
  SHA-256 manifest, verified copy, schema migration and crash recovery.
- Export records all preserved user-owned Settings, Library/ACSDB, Books,
  Training, Classroom, Media, Agent and Accounts paths without inventing
  new chess-state owners. Canonical runtime locks/temps are deliberately excluded.
- Import accepts an existing owner-transfer snapshot under its
  `*.upgrade-backups` parent, authenticates the manifest and every copy,
  migrates only a private staging profile, then atomically publishes using
  the existing non-replacing directory mechanism.
- Import requires an entirely new profile name **and** no pre-existing
  matching backup-history directory. Existing user data is never overwritten.
- Snapshots can contain private user text and provider settings. Treat them
  as sensitive data; keep them on trusted encrypted personal storage, not
  in the repository or in public release ZIPs.

## Keyboard / text workflow

Close the running Accessible Chess application before producing a full backup.
Then run the following in a command prompt with Python and the project source
installed, replacing example paths:

```text
python -m acs.user_data_transfer export --root "C:\\Users\\USER\\AppData\\Local\\AccessibleChess"
```

The command prints one JSON result containing `status` and `snapshot`.
Keep the entire `AccessibleChess.upgrade-backups` directory hierarchy
when moving the new snapshot to another computer.

To transfer into a NEW name (never an existing data directory):

```text
python -m acs.user_data_transfer import --backup "D:\\Transfer\\AccessibleChess.upgrade-backups\\owner-transfer-<exact-id>" --target "C:\\Users\\USER\\AppData\\Local\\AccessibleChess"
```

A refusal leaves an existing destination profile untouched. Import's first
startup migration does not require overwriting a prior owner installation.
If an abandoned **new** backup-history directory remains after publication
failure, inspect the situation before retrying; do not delete any owner data.

The CLI supports screen readers through ordinary console text/JSON. This
source Python entrypoint does not establish a button in the shipped Windows
application or provide the final installer workflow. Media/Agent settings
that reference machine-specific external file locations may require user
relinking; preserved bytes alone do not establish cross-machine playback.

## Acceptance and evidence

- `tests/test_section51_cross_surface_recovery.py`: 7 scenarios for
  full-domain backup/restart, schema-1 upgrade, future-schema refusal,
  rollback/crash retry and corrupt-copy denial.
- `tests/test_section51_owner_data_transfer.py`: 6 scenarios for actual
  transfer, tamper/traversal rejection, preexisting destination protection,
  future-schema refusal and backup-history protection.
- `.github/workflows/section51-cross-surface-recovery.yml`: exact-head
  Ubuntu and Windows unittest + retained upgrade suites + selftest.

**Execution state at checkpoint:** source committed to draft PR #2531;
new regression tests have not been reported terminal PASS by GitHub Actions.
Queued is not green. Do not merge or mark Section 51 DONE based on source
presence alone. Additional acceptance must cover app-level export/import
accessibility, cross-version release matrix, clean-machine Windows and owner
NVDA checks.
