# DEV4 SESSION HANDOFF

SESSION: 20260822-0802 Full Product QA/security
STATUS: COMPLETE / SAFE OVERLAP

## Exact branches and SHAs

- DEV4 Stage1 Product source: `manual5/dev4-platform-security-packaging-20260821` @ `a4209d005ea0a1476f8eafb4822f4d39ac50ee5a`.
- Manual5 integration: `manual5/integration-20260821` @ `0fa442330bc2bb03636ff9297512da4c29e38684`.
- DEV5 reconciliation draft PR #66: `manual5/dev5-reconcile-dev4-20260822` @ `abff45ebcc4b5af2a85ab0c456b025b5098c6e29`, OPEN/DRAFT.
- DEV4 QA evidence branch: `qa/dev4-chessbase-symlink-security-20260822`.
- New QA evidence commit: `7b97c1e46e52c1691b59c24949a76656be1b2a33` — `test(qa): lock Stockfish error path privacy`.
- QA draft PR #67 remains OPEN/DRAFT/MERGEABLE. Metadata commits after the evidence commit advance the branch; use live PR #67 head as the final exact QA SHA.

## Live CI / evidence discipline

Manual5 integration exact SHA `0fa442330bc2bb03636ff9297512da4c29e38684` retains prior SUCCESS evidence:
- UI Semantic Gate `32532577650`.
- Stage1 Saturation Hardening `32532577641`.

Exact workflow runs for evidence commit `7b97c1e46e52c1691b59c24949a76656be1b2a33`: none observed. QA CI therefore remains INCONCLUSIVE, never inferred GREEN. Existing integration/DEV5 GREEN does not validate QA-only external-format/privacy assertions.

## New QA evidence — Stockfish/UCI path privacy

Low-level `UCIEngine`/`StockfishRuntime` exception text can legitimately contain filesystem/executable details for internal diagnostics. Release-facing APIs must not expose those details to screen-reader/WebView output.

`tests/test_dev4_engine_error_path_privacy.py` injects a provider failure containing synthetic private path `C:\\Users\\qa-user\\secret-build\\stockfish.exe` during engine-game startup and asserts the release response omits both the full path and private path components while retaining a concise Stockfish-facing error.

Source inspection of `Stage1ReleaseAccessibleChessAPI.start_engine_game()` and `_request_engine_reply()` confirms provider exceptions are caught and replaced with concise localized messages rather than `str(exc)`. This is positive privacy/non-regression evidence, not a new Product defect.

## Locked PROVEN_PRODUCT_DEFECT findings

1. Import/ChessBase symlink/reparse indirection is followed instead of failing closed.
2. PGN import uses an unbounded full-text `handle.read()` after bounded hashing.
3. ChessBase serialized probe/integrity/manifest payloads expose absolute local paths.
4. PGN `expected_sha256` optimistic-concurrency commit race can overwrite newer content.
5. PGN `overwrite=False` commit race can clobber a destination created after preflight.
6. PGN export filesystem indirection is not fail-closed; direct parent, deeper ancestor and destination symlinks are covered by strict QA evidence.

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

Recheck live PR #67 exact head and Actions after metadata commits. Continue generic import size/encoding/cancellation/resource-limit evidence and direct path/error sink tracing. Extend engine/UCI privacy guards only where a real user-facing surface is involved. Continue ChessBase unknown-version/resource-boundary evidence without inventing proprietary semantics. Re-enter Stage1 package work only through DEV5/Audit-authorized reconciliation.
