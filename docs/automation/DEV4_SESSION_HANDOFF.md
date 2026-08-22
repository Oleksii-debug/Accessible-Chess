# DEV4 SESSION HANDOFF

SESSION: 20260822-0900 Full Product QA/security
STATUS: COMPLETE / SAFE OVERLAP

## Exact branches and SHAs

- DEV4 Stage1 Product source: `manual5/dev4-platform-security-packaging-20260821` @ `a4209d005ea0a1476f8eafb4822f4d39ac50ee5a`.
- Manual5 integration: `manual5/integration-20260821` @ `0fa442330bc2bb03636ff9297512da4c29e38684`.
- DEV5 reconciliation draft PR #66: `manual5/dev5-reconcile-dev4-20260822` @ `abff45ebcc4b5af2a85ab0c456b025b5098c6e29`, OPEN/DRAFT.
- DEV4 QA evidence branch: `qa/dev4-chessbase-symlink-security-20260822`.
- New QA evidence commit: `7aaf647b13f98fb45cbdb4ba900b497ff1bcc20b` — `test(qa): gate ChessBase companion probe false-green`.
- QA draft PR #67 remains OPEN/DRAFT/MERGEABLE. Metadata commits after the evidence commit advance the branch; use live PR #67 head as the final exact QA SHA.

## Live CI / evidence discipline

Manual5 integration exact SHA `0fa442330bc2bb03636ff9297512da4c29e38684` retains prior SUCCESS evidence:
- UI Semantic Gate `32532577650`.
- Stage1 Saturation Hardening `32532577641`.

Exact QA-head checks must be re-read after handoff metadata commits. Absence of commit-associated Actions is INCONCLUSIVE, never inferred GREEN. Existing integration/DEV5 GREEN does not validate QA-only external-format/security assertions.

## New PROVEN_PRODUCT_DEFECT — ChessBase companion probe false-green

`acs.chessbase_adapter._case_insensitive_directory_index()` catches `OSError` from directory enumeration and returns an empty index. `probe_chessbase_source()` then emits the same `No classic CBH companion files were detected beside the header` warning used for a successful enumeration that genuinely found no companions.

This collapses `inspection unavailable` into `verified absent`, creating false-green provenance. A permission/I/O failure cannot prove companion absence.

Strict QA gate `tests/test_dev4_chessbase_probe_observability.py` injects `PermissionError` at the directory enumeration boundary and requires the probe to avoid the normal no-companion claim and surface explicit unavailable/access/I/O evidence. Product code is unchanged.

Classification: `PROVEN_PRODUCT_DEFECT`.

## Locked PROVEN_PRODUCT_DEFECT findings

1. Import/ChessBase symlink/reparse indirection is followed instead of failing closed.
2. PGN import uses an unbounded full-text `handle.read()` after bounded hashing.
3. ChessBase serialized probe/integrity/manifest payloads expose absolute local paths.
4. PGN `expected_sha256` optimistic-concurrency commit race can overwrite newer content.
5. PGN `overwrite=False` commit race can clobber a destination created after preflight.
6. PGN export filesystem indirection is not fail-closed; direct parent, deeper ancestor and destination symlinks are covered by strict QA evidence.
7. ChessBase CBH companion directory I/O failures are reported as ordinary no-companion evidence instead of explicit unavailable/error state.

## Additional classifications

- QA EVIDENCE: PGN export failure-recovery assertions preserve existing destination/temp cleanup and POSIX temp privacy.
- QA EVIDENCE: Stockfish provider path-bearing exceptions are sanitized at the release API boundary.
- INCONCLUSIVE: exact QA-head CI until checks are observed.
- INCONCLUSIVE: PGN parent-directory durability across crash/power loss.
- INCONCLUSIVE: generic `SourceFingerprint.path`, `BatchInspectionItem.path/error` and PGN exception strings reaching real UI/persistence/report sinks beyond already-proven ChessBase DTO leakage.
- HUMAN_ONLY: exact fresh Windows native-menu/NVDA usability. `NVDA_VERIFIED=NO`.

## Preserved findings / boundaries

- `docs/automation/DEV4_CHESSBASE_CAPABILITY_MATRIX.md` remains evidence-only and does not infer proprietary decoder compatibility from suffix recognition.
- PROVEN_PRODUCT_INTEGRATION_RISK: preserve accepted DEV1/integration `web/stage1_board_actions.js` semantics.
- PROVEN_RELEASE_PIPELINE_BLOCKER: `nuitka-compilation-report.xml` must remain CI evidence only and stay out of user ZIPs.
- No Ctrl+A/Ctrl+C Product defect claim.
- Windows strict WIP=1 respected.
- No force-push, DEV5/integration mutation, `tools/qa` or strict Windows workflow edit, DEV3 ACSDB performance takeover, frozen-release merge or Windows candidate.

## Next action

Recheck live PR #67 exact head and Actions after metadata commits. Continue generic import resource-limit evidence and ChessBase component-open/stat/hash observability so inaccessible evidence is never represented as absent or healthy. Continue direct path/error sink tracing and user-facing engine privacy guards only where evidence is concrete. Re-enter Stage1 package work only through DEV5/Audit-authorized reconciliation.
