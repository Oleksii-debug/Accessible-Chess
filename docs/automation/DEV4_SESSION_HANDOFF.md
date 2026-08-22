# DEV4 SESSION HANDOFF

SESSION: 20260822-1000 Full Product QA/security
STATUS: COMPLETE / SAFE OVERLAP

## Exact branches and SHAs

- DEV4 Stage1 Product source: `manual5/dev4-platform-security-packaging-20260821` @ `a4209d005ea0a1476f8eafb4822f4d39ac50ee5a`.
- Manual5 integration: `manual5/integration-20260821` @ `0fa442330bc2bb03636ff9297512da4c29e38684`.
- DEV5 reconciliation draft PR #66: `manual5/dev5-reconcile-dev4-20260822` @ `abff45ebcc4b5af2a85ab0c456b025b5098c6e29`, OPEN/DRAFT.
- DEV4 QA evidence branch: `qa/dev4-chessbase-symlink-security-20260822`.
- New QA evidence commit: `bb685bdccdb6666060fd2271c8760f31496453e6` — `test(qa): gate non-aborting import adapter failures`.
- QA draft PR #67 remains OPEN/DRAFT/MERGEABLE. Metadata synchronization commits follow the evidence commit; canonical Drive handoff records the final exact live QA head.

## Live CI / evidence discipline

Manual5 integration exact SHA `0fa442330bc2bb03636ff9297512da4c29e38684` retains prior SUCCESS evidence:
- UI Semantic Gate `32532577650`.
- Stage1 Saturation Hardening `32532577641`.

Exact QA-head checks were absent before metadata synchronization. Absence is `INCONCLUSIVE`, never inferred GREEN. Existing integration/DEV5 GREEN does not validate QA-only external-format/security assertions.

## New PROVEN_PRODUCT_DEFECT — non-aborting import batch contract breaks on RuntimeError

`ImportRegistry.inspect_batch()` explicitly describes a preferred non-aborting multi-file preflight in which adapter errors are recorded against the failing source while remaining sources are still inspected. The implementation catches `ImportRegistryError`, `OSError`, and `ValueError` only. An importer/decoder/provider that raises `RuntimeError` escapes the method and aborts the batch.

Strict QA gate `tests/test_dev4_import_batch_adapter_failure.py` registers a RuntimeError-producing first importer and a healthy second importer. It requires the first source to become a failed `BatchInspectionItem` and the second source to remain successfully inspected. Product code is unchanged.

Classification: `PROVEN_PRODUCT_DEFECT` because the live implementation contradicts its explicit batch-continuation/evidence contract.

## Locked PROVEN_PRODUCT_DEFECT findings

1. Import/ChessBase symlink/reparse indirection is followed instead of failing closed.
2. PGN import uses an unbounded full-text `handle.read()` after bounded hashing.
3. ChessBase serialized probe/integrity/manifest payloads expose absolute local paths.
4. PGN `expected_sha256` optimistic-concurrency commit race can overwrite newer content.
5. PGN `overwrite=False` commit race can clobber a destination created after preflight.
6. PGN export filesystem indirection is not fail-closed.
7. ChessBase CBH companion directory I/O failures are reported as ordinary no-companion evidence instead of explicit unavailable/error state.
8. Generic import batch preflight aborts on importer `RuntimeError` instead of recording the failed source and continuing later sources.

## Additional classifications

- QA EVIDENCE: PGN export failure-recovery assertions preserve existing destination/temp cleanup and POSIX temp privacy.
- QA EVIDENCE: Stockfish provider path-bearing exceptions are sanitized at the release API boundary.
- INCONCLUSIVE: exact QA-head CI until checks are observed.
- INCONCLUSIVE: PGN parent-directory durability across crash/power loss.
- INCONCLUSIVE: generic provenance/error strings reaching real UI/persistence/report sinks beyond already-proven ChessBase DTO leakage.
- HUMAN_ONLY: exact fresh Windows native-menu/NVDA usability. `NVDA_VERIFIED=NO`.

## Preserved findings / boundaries

- `docs/automation/DEV4_CHESSBASE_CAPABILITY_MATRIX.md` remains evidence-only and does not infer proprietary decoder compatibility from suffix recognition.
- PROVEN_PRODUCT_INTEGRATION_RISK: preserve accepted DEV1/integration `web/stage1_board_actions.js` semantics.
- PROVEN_RELEASE_PIPELINE_BLOCKER: `nuitka-compilation-report.xml` must remain CI evidence only and stay out of user ZIPs.
- No Ctrl+A/Ctrl+C Product defect claim.
- Windows strict WIP=1 respected.
- No force-push, DEV5/integration mutation, `tools/qa` or strict Windows workflow edit, DEV3 ACSDB performance takeover, frozen-release merge or Windows candidate.

## Next action

Recheck live PR #67 exact head and Actions after metadata synchronization. Continue generic import resource-limit evidence and ChessBase component-open/stat/hash observability; continue direct path/error sink tracing only where user-facing/persisted evidence is concrete. Re-enter Stage1 package work only through DEV5/Audit-authorized reconciliation.
