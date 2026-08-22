# DEV4 SESSION HANDOFF

SESSION: 20260822-0657 Full Product QA/security
STATUS: COMPLETE / SAFE OVERLAP

## Exact branches and SHAs

- DEV4 Stage1 Product source: `manual5/dev4-platform-security-packaging-20260821` @ `a4209d005ea0a1476f8eafb4822f4d39ac50ee5a`.
- Manual5 integration: `manual5/integration-20260821` @ `0fa442330bc2bb03636ff9297512da4c29e38684`.
- DEV5 reconciliation draft PR #66: `manual5/dev5-reconcile-dev4-20260822` @ `abff45ebcc4b5af2a85ab0c456b025b5098c6e29`, OPEN/DRAFT.
- DEV4 QA evidence branch: `qa/dev4-chessbase-symlink-security-20260822`.
- New QA evidence commit: `bb15c7f564114a09599600d0bbe99edd5bbd9f27` — `test(qa): lock PGN export failure recovery`.
- QA draft PR #67 remains OPEN/DRAFT. Metadata/doc commits after the evidence commit advance the branch; use live PR #67 head as the final exact QA branch SHA.

## Live CI / evidence discipline

Manual5 integration exact SHA `0fa442330bc2bb03636ff9297512da4c29e38684` retains prior SUCCESS evidence:
- UI Semantic Gate `32532577650`.
- Stage1 Saturation Hardening `32532577641`.

QA branch exact-head CI must be re-read after the metadata commits. Absence of commit-associated Actions is INCONCLUSIVE, never inferred GREEN. Existing integration/DEV5 GREEN does not validate QA-only external-format assertions.

## New QA evidence — PGN export recovery

`tests/test_dev4_pgn_export_failure_recovery.py` adds non-conflicting failure-path regression coverage around the existing `save_pgn_atomic()` implementation:

1. if `os.replace()` raises, the pre-existing destination must remain byte-for-byte intact and the generated temp file must be removed;
2. if temp-file `os.fsync()` raises, the pre-existing destination must remain intact and the incomplete temp file must be removed;
3. on POSIX, the temp PGN must not be group/world-readable before atomic replacement. Windows ACL semantics are not represented by this mode-bit assertion and are not falsely claimed.

Product source is intentionally unchanged. This run does not promote a new Product defect from these paths; it adds positive recovery/non-regression evidence while preserving the six already-proven defect classes.

## Locked PROVEN_PRODUCT_DEFECT findings

1. Import/ChessBase symlink/reparse indirection is followed instead of failing closed.
2. PGN import uses an unbounded full-text `handle.read()` after bounded hashing.
3. ChessBase serialized probe/integrity/manifest payloads expose absolute local paths.
4. PGN `expected_sha256` optimistic-concurrency commit race can overwrite newer content.
5. PGN `overwrite=False` commit race can clobber a destination created after preflight.
6. PGN export filesystem indirection is not fail-closed; direct parent, deeper ancestor and destination symlinks are covered by strict QA evidence.

## Additional classifications

- INCONCLUSIVE: exact QA-head CI until checks are observed.
- INCONCLUSIVE: parent-directory durability across crash/power loss; file `fsync` alone is not treated as proof of directory-entry durability.
- INCONCLUSIVE: generic `SourceFingerprint.path`, `BatchInspectionItem.path/error` and PGN exception path strings reaching actual UI/persistence/report sinks beyond already-proven ChessBase DTO leakage.
- HUMAN_ONLY: exact fresh Windows native-menu/NVDA usability. `NVDA_VERIFIED=NO`.

## Preserved findings / boundaries

- `docs/automation/DEV4_CHESSBASE_CAPABILITY_MATRIX.md` remains evidence-only and does not infer proprietary decoder compatibility from suffix recognition.
- PROVEN_PRODUCT_INTEGRATION_RISK: preserve accepted DEV1/integration `web/stage1_board_actions.js` semantics.
- PROVEN_RELEASE_PIPELINE_BLOCKER: `nuitka-compilation-report.xml` must remain CI evidence only and stay out of user ZIPs.
- No Ctrl+A/Ctrl+C Product defect claim.
- Windows strict WIP=1 respected.
- No force-push, DEV5/integration mutation, `tools/qa` or strict Windows workflow edit, DEV3 ACSDB performance takeover, frozen-release merge or Windows candidate.

## Next action

Recheck live PR #67 exact head and Actions. Continue generic import size/encoding/cancellation limits and end-to-end path/error exposure tracing; keep PGN directory durability conservative unless reproducible evidence establishes a contract violation. Continue ChessBase unknown-version/resource-boundary evidence without inventing proprietary semantics. Re-enter Stage1 package work only through DEV5/Audit-authorized reconciliation.
