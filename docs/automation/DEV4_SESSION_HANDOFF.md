# DEV4 SESSION HANDOFF

SESSION: 20260822-2100 Full Product repair
STATUS: COMPLETE_WITH_CI_UNOBSERVED
ROLE: DEV4 Product Developer
DIRECTIVE: AUDIT-20260822-1900-01
NVDA_VERIFIED=NO

## Exact state basis

- Product branch: `full5/dev4-import-security-repair-20260822`.
- New implementation commit: `f37ce643f86871d3680f376ff220502a2390cdc2`.
- New Product regression commit: `7d063008bb145a7a9012d442f6af13ef258b40c1`.
- QA gate maintenance commit: `1d90557905753b158b99b7d62321a5e1f1a423bb` on `qa/dev4-chessbase-symlink-security-20260822`; assertion semantics preserved while injection moved to real no-clobber primitive.
- Draft Product PR #100 targets `manual5/dev4-platform-security-packaging-20260821`.
- QA PR #67 remains separate; strict evidence is preserved.
- Accepted Stage1 integration remains `0fa442330bc2bb03636ff9297512da4c29e38684`; untouched.
- DEV5 PR #66 remains `abff45ebcc4b5af2a85ab0c456b025b5098c6e29`; untouched.
- Exact Product-head Actions are absent at checkpoint: `INCONCLUSIVE`, not GREEN.
- Windows strict WIP=1 untouched.

## New Product repairs

1. `overwrite=False` publication no longer uses replace. The complete same-directory temp file is linked into the destination name atomically; if another writer creates that name first, `os.link` fails with `FileExistsError` and the competing file is preserved.
2. `expected_sha256` publication now creates a hard-link snapshot of the current destination inode, rechecks the expected digest immediately before publication, and keeps that inode recoverable across `os.replace`. If an in-place racing writer changes that inode during the final window, the snapshot digest changes; its bytes are restored to the destination and `PgnConcurrentWriteError` is raised.
3. Product tests now deterministically cover both publication races. The QA no-overwrite gate was updated only to follow the new `os.link` publication primitive; the required outcome remains unchanged.

## Previous repairs retained

Stable fail-closed import fingerprinting, bounded PGN reads, lossy UTF-8 quality downgrade, per-source RuntimeError isolation, ChessBase report path privacy, companion I/O observability, stable integrity snapshots, manifest verification I/O handling, unsafe-indirection rejection, ACSDB error privacy and PGN export path-indirection rejection.

## Classification

- Previously proven expected-hash and no-overwrite race scenarios now have Product repair plus regression coverage.
- Generic non-cooperative external atomic inode replacement during the narrow CAS window remains `INCONCLUSIVE`; no portable universal CAS claim is made.
- Missing PGN termination-marker quality remains proven QA evidence but overlaps DEV2 GameTree ownership.
- Exact PR #100 CI: `INCONCLUSIVE` until observed.
- Windows reparse/hard-link behavior: `INCONCLUSIVE` until exact Windows execution.
- NVDA usability: `HUMAN_ONLY`; `NVDA_VERIFIED=NO`.
- No tests weakened. No Ctrl+A/Ctrl+C Product defect claim.

## Next action

Read PR #100 final head/CI first. Inspect publication cleanup/durability and hard-link failure mapping without entering DEV5/integration, strict Windows, Stage1 release or DEV2 GameTree ownership.