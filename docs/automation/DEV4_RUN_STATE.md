# DEV4 RUN STATE

RUN_ID: 20260822-0802-full-product-qa
STATUS: COMPLETE
MODE: SAFE_OVERLAP_QA_EVIDENCE
ROLE: DEV4 independent QA/evidence/security

## Live snapshot

- DEV4 Stage1 Product source: `manual5/dev4-platform-security-packaging-20260821` @ `a4209d005ea0a1476f8eafb4822f4d39ac50ee5a`.
- Manual5 integration remains `manual5/integration-20260821` @ `0fa442330bc2bb03636ff9297512da4c29e38684`; prior exact UI Semantic Gate `32532577650` and Stage1 Saturation `32532577641` remain SUCCESS evidence for that integration SHA.
- DEV5 reconciliation PR #66 remains OPEN/DRAFT at `abff45ebcc4b5af2a85ab0c456b025b5098c6e29`; DEV4 did not modify that owner lane.
- DEV4 QA branch: `qa/dev4-chessbase-symlink-security-20260822`.
- New non-conflicting QA evidence commit: `7b97c1e46e52c1691b59c24949a76656be1b2a33` — `test(qa): lock Stockfish error path privacy`.
- QA PR #67 remains OPEN/DRAFT/MERGEABLE.
- Exact evidence-commit workflow runs: none observed. Classification: INCONCLUSIVE CI observability, not GREEN.
- `AGENTS.md` and `docs/codex/CURRENT_STATE.md` remain absent on the checked QA ref; operative state is live GitHub plus `docs/automation/DEV4_*` and canonical Drive handoff.
- Windows strict WIP=1 remains untouched. `NVDA_VERIFIED=NO`.

## New QA evidence — Stockfish/UCI error path privacy

Low-level engine/runtime code may include executable/filesystem paths inside internal exception text. The release API is deliberately required to prevent those details from becoming WebView/NVDA output.

Added `tests/test_dev4_engine_error_path_privacy.py` without Product mutation. The test injects a provider failure containing a synthetic private Windows path (`C:\\Users\\qa-user\\secret-build\\stockfish.exe`) during engine-game startup and requires the release-facing result to:

1. fail safely;
2. omit the full private path;
3. omit private path components (`qa-user`, `secret-build`);
4. retain a concise Stockfish-facing user message.

Source inspection confirms `Stage1ReleaseAccessibleChessAPI.start_engine_game()` and engine-reply failure handling convert provider exceptions into concise localized messages rather than returning `str(exc)`. This is positive QA/privacy evidence, not a new Product defect claim.

## Locked PROVEN_PRODUCT_DEFECT findings

1. External import/ChessBase symlink-reparse indirection follows filesystem targets instead of failing closed.
2. PGN import performs an unbounded full-text `handle.read()` after bounded hashing.
3. Serialized ChessBase probe/integrity/manifest DTOs expose absolute/local paths.
4. PGN `expected_sha256` optimistic overwrite has a TOCTOU lost-update window.
5. PGN `overwrite=False` can clobber a destination created after preflight.
6. PGN export path handling accepts filesystem indirection instead of failing closed; strict coverage includes direct-parent, deeper-ancestor and destination-file symlinks.

## Other classifications / boundaries

- QA EVIDENCE: PGN export recovery guard preserves destination/temp cleanup across injected `os.replace`/`os.fsync` failures and checks POSIX private temp mode.
- QA EVIDENCE: Stockfish provider path-bearing failures are sanitized at the release API boundary before WebView/NVDA output.
- INCONCLUSIVE: exact QA-head CI until commit-associated checks are observed; absence is not GREEN.
- INCONCLUSIVE: parent-directory durability across crash/power loss.
- INCONCLUSIVE: generic `SourceFingerprint.path`, `BatchInspectionItem.path/error` and PGN exception strings reaching actual UI/persisted surfaces beyond already-proven ChessBase DTO leakage.
- HUMAN_ONLY: exact fresh Windows native-menu/NVDA usability; `NVDA_VERIFIED=NO`.
- PROVEN_PRODUCT_INTEGRATION_RISK: preserve accepted DEV1/integration `web/stage1_board_actions.js` semantics during reconciliation.
- PROVEN_RELEASE_PIPELINE_BLOCKER: `nuitka-compilation-report.xml` may remain CI evidence only and must not ship in a user ZIP.
- No Product Ctrl+A/Ctrl+C defect is claimed.
- No force-push, DEV5/integration mutation, `tools/qa` or strict Windows workflow edit, frozen-release merge, Windows candidate creation, or DEV3 ACSDB performance takeover occurred.

## Next action

1. Re-read PR #67 exact head and Actions after handoff metadata commits.
2. Continue generic import resource-limit evidence: explicit source caps, huge/truncated content, encoding abuse, duplicate-source behavior, cancellation and recovery.
3. Trace generic import/provenance errors into real persisted/UI/report sinks; promote only direct exposure.
4. Audit additional UCI/engine failure surfaces to ensure private executable/path data remains internal while preserving useful diagnostics.
5. Continue ChessBase unknown-version/resource-boundary evidence without inventing proprietary decoder semantics.
6. Re-enter Stage1 package/security only through DEV5/Audit-authorized reconciliation.
