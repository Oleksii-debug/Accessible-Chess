# DEV4 SESSION HANDOFF

SESSION: 20260822-0402 Full Product QA/security
STATUS: COMPLETE / SAFE OVERLAP

## Exact branches and SHAs

- DEV4 Stage1 Product source: `manual5/dev4-platform-security-packaging-20260821` @ `a4209d005ea0a1476f8eafb4822f4d39ac50ee5a`.
- Manual5 integration: `manual5/integration-20260821` @ `0fa442330bc2bb03636ff9297512da4c29e38684`.
- DEV5 reconciliation draft PR #66: `manual5/dev5-reconcile-dev4-20260822` @ `abff45ebcc4b5af2a85ab0c456b025b5098c6e29`.
- DEV4 QA evidence branch: `qa/dev4-chessbase-symlink-security-20260822`.
- New security evidence commit: `9f7ed301743aa049695fc667497993ca58155cf1` — `test(security): gate PGN export symlink-parent escape`.
- Handoff commits in this run: `fc2bee483a03bfe2ebc9733b5775223bba9f74f2`, `e845b4689501f841faefa62ec5392095fe01c4cd`; verify live final branch head after this file update.
- QA draft PR: #67, OPEN/DRAFT.

## Live CI

Manual5 integration exact SHA `0fa442330bc2bb03636ff9297512da4c29e38684`:
- UI Semantic Gate `32532577650` — SUCCESS.
- Stage1 Saturation Hardening `32532577641` — SUCCESS.

DEV4 QA exact head `9f7ed301743aa049695fc667497993ca58155cf1` had no observed commit-associated Actions before handoff-only commits. Classification: INCONCLUSIVE CI observability, not GREEN. Existing integration/DEV5 GREEN does not cover QA-only external-format assertions.

## Repository instruction discovery

`AGENTS.md` and `docs/codex/CURRENT_STATE.md` remain absent on the checked QA ref. Canonical Drive RUN_STATE/current/next/session files were read before this continuation; live GitHub remains technical truth.

## New finding

### PROVEN_PRODUCT_DEFECT — PGN export follows symlink/reparse parent and escapes submitted directory tree

`save_pgn_atomic()` does not reject a destination whose parent directory is filesystem indirection. It passes `destination.parent` to `NamedTemporaryFile`, then uses `os.replace(tmp_path, destination)`. If the submitted parent is a symlink/reparse-style link to another directory, both temp creation and final commit occur in that target directory.

DEV4 independently reproduced the filesystem transition with `submitted/exports -> external/`: the current operation creates `external/escaped.pgn`.

Strict regression: `tests/test_dev4_pgn_export_path_security.py`. The gate requires fail-closed rejection before any file is created through the indirect parent. Product source is intentionally unchanged.

QA evidence commit:
- `9f7ed301743aa049695fc667497993ca58155cf1` — `test(security): gate PGN export symlink-parent escape`.

## Previously locked defects

1. Import/ChessBase symlink/reparse indirection is followed instead of failing closed.
2. PGN import uses an unbounded full-text `handle.read()` after bounded hashing.
3. ChessBase serialized probe/integrity/manifest payloads expose absolute local paths.
4. PGN `expected_sha256` optimistic-concurrency commit race can overwrite newer content.
5. PGN `overwrite=False` commit race can clobber a destination created after preflight.

## Preserved findings / boundaries

- `docs/automation/DEV4_CHESSBASE_CAPABILITY_MATRIX.md` remains evidence-only and does not infer proprietary decoder compatibility from suffix recognition.
- PROVEN_PRODUCT_INTEGRATION_RISK: preserve accepted DEV1/integration `web/stage1_board_actions.js` semantics.
- PROVEN_RELEASE_PIPELINE_BLOCKER: `nuitka-compilation-report.xml` must remain CI evidence only and stay out of user ZIPs.
- HUMAN_ONLY: exact fresh Windows native-menu/NVDA usability. `NVDA_VERIFIED=NO`.
- No Ctrl+A/Ctrl+C Product defect claim.
- Windows strict WIP=1 respected.
- No force-push, DEV5/integration mutation, `tools/qa` or strict Windows workflow edit, DEV3 ACSDB performance takeover, frozen release merge or Windows candidate.

## Next action

Recheck final QA branch head and PR #67 Actions. Continue destination-file symlink/parent-chain and PGN temp/fsync/replace/durability failure recovery, then generic import size/encoding/cancellation limits and end-to-end path/error exposure tracing. Continue ChessBase unknown-version/resource-boundary evidence without inventing proprietary semantics. Re-enter Stage1 package work only through DEV5/Audit-authorized reconciliation.
