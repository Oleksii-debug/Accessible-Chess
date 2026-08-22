# DEV4 RUN STATE

RUN_ID: 20260822-0657-full-product-qa
STATUS: COMPLETE
MODE: SAFE_OVERLAP_QA_EVIDENCE
ROLE: DEV4 independent QA/evidence/security

## Live snapshot

- DEV4 Stage1 Product source: `manual5/dev4-platform-security-packaging-20260821` @ `a4209d005ea0a1476f8eafb4822f4d39ac50ee5a`.
- Manual5 integration remains `manual5/integration-20260821` @ `0fa442330bc2bb03636ff9297512da4c29e38684`; prior exact UI Semantic Gate `32532577650` and Stage1 Saturation `32532577641` are SUCCESS.
- DEV5 reconciliation draft PR #66 remains OPEN/DRAFT at `abff45ebcc4b5af2a85ab0c456b025b5098c6e29`; DEV4 did not modify that owner lane.
- DEV4 QA branch: `qa/dev4-chessbase-symlink-security-20260822`.
- New non-conflicting QA evidence commit: `bb15c7f564114a09599600d0bbe99edd5bbd9f27` — `test(qa): lock PGN export failure recovery`.
- DEV4 QA draft PR #67 remains OPEN/DRAFT.
- Requested `AGENTS.md` and `docs/codex/CURRENT_STATE.md` remain absent on the checked QA ref; operative state remains live GitHub + canonical Drive + `docs/automation/DEV4_*`.
- Windows strict WIP=1 remains untouched. `NVDA_VERIFIED=NO`.

## New QA evidence — PGN export failure recovery

Added `tests/test_dev4_pgn_export_failure_recovery.py` without Product mutation. It locks three recovery/security invariants around the existing atomic-save path:

1. injected `os.replace()` failure must preserve an existing destination and clean the generated `.tmp` file;
2. injected temp-file `os.fsync()` failure must preserve an existing destination and clean the generated `.tmp` file;
3. on POSIX, the temp PGN must not expose group/world permission bits before commit. Windows ACL semantics are intentionally not inferred from POSIX mode bits.

This slice is positive evidence/non-regression coverage, not a new Product defect claim. The current `finally` cleanup structure is consistent with the first two invariants by inspection; exact QA-head CI still must be observed before calling the branch GREEN.

## Locked PROVEN_PRODUCT_DEFECT findings

1. External import/ChessBase symlink-reparse indirection follows filesystem targets instead of failing closed.
2. PGN import performs an unbounded full-text `handle.read()` after bounded hashing.
3. Serialized ChessBase probe/integrity/manifest DTOs expose absolute/local paths.
4. PGN `expected_sha256` optimistic overwrite has a TOCTOU lost-update window.
5. PGN `overwrite=False` can clobber a destination created after preflight.
6. PGN export path handling accepts filesystem indirection instead of failing closed; strict coverage includes direct-parent, deeper-ancestor and destination-file symlinks.

## Other classifications / boundaries

- INCONCLUSIVE: exact QA-head CI until commit-associated checks are observed; absence is not GREEN.
- INCONCLUSIVE: parent-directory durability across crash/power loss; file `fsync` alone is not promoted to a stronger durability claim.
- INCONCLUSIVE: generic `SourceFingerprint.path`, `BatchInspectionItem.path/error` and PGN exception strings reaching actual UI/persisted surfaces beyond already-proven ChessBase DTO leakage.
- HUMAN_ONLY: exact fresh Windows native-menu/NVDA usability; `NVDA_VERIFIED=NO`.
- PROVEN_PRODUCT_INTEGRATION_RISK: preserve accepted DEV1/integration `web/stage1_board_actions.js` semantics during reconciliation.
- PROVEN_RELEASE_PIPELINE_BLOCKER: `nuitka-compilation-report.xml` may remain CI evidence only and must not ship in a user ZIP.
- No Product Ctrl+A/Ctrl+C defect is claimed.
- No force-push, DEV5/integration mutation, `tools/qa` or strict Windows workflow edit, frozen-release merge, Windows candidate creation, or DEV3 ACSDB performance takeover occurred.

## Next action

1. Recheck QA PR #67 exact head and commit-associated Actions without treating absence as GREEN.
2. Continue PGN commit-safety audit with parent-directory durability classified conservatively and deterministic serialization/error-surface tracing.
3. Continue generic import resource limits: explicit size caps, huge/truncated content, encoding abuse, duplicate sources, cancellation and recovery.
4. Trace generic provenance/error paths into real persisted/UI/report sinks; classify only direct exposure.
5. Continue ChessBase unknown-version/resource-boundary evidence without inventing proprietary decoder semantics.
6. Re-enter Stage1 package/security only through DEV5/Audit-authorized reconciliation.
