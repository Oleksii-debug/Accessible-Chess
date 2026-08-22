# DEV4 SESSION HANDOFF

SESSION: 20260822-0600 Full Product QA/security
STATUS: COMPLETE / SAFE OVERLAP

## Exact branches and SHAs

- DEV4 Stage1 Product source: `manual5/dev4-platform-security-packaging-20260821` @ `a4209d005ea0a1476f8eafb4822f4d39ac50ee5a`.
- Manual5 integration: `manual5/integration-20260821` @ `0fa442330bc2bb03636ff9297512da4c29e38684` (live compare IDENTICAL).
- DEV5 reconciliation draft PR #66: `manual5/dev5-reconcile-dev4-20260822` @ `abff45ebcc4b5af2a85ab0c456b025b5098c6e29`, OPEN/DRAFT.
- DEV4 QA evidence branch: `qa/dev4-chessbase-symlink-security-20260822`.
- New security evidence commit: `5715b167500bb88287c41f1354f20d05c0fd29a1` — `test(security): extend PGN export path-indirection gate`.
- This handoff update itself advances the QA branch; use live PR #67 head as final exact branch SHA.
- QA draft PR #67 remains OPEN/DRAFT.

## Live CI

Manual5 integration exact SHA `0fa442330bc2bb03636ff9297512da4c29e38684`:
- UI Semantic Gate `32532577650` — SUCCESS.
- Stage1 Saturation Hardening `32532577641` — SUCCESS.

QA evidence commit `5715b167500bb88287c41f1354f20d05c0fd29a1` had no observed commit-associated Actions at continuation time. Classification: INCONCLUSIVE CI observability, not GREEN. Existing integration/DEV5 GREEN does not cover QA-only external-format assertions.

## Repository instruction discovery

`AGENTS.md` and `docs/codex/CURRENT_STATE.md` remain absent on the checked QA ref. Repository search did not surface `docs/codex/NEXT_WORK.md` or `docs/codex/SESSION_HANDOFF.md`. Operative state therefore remains live GitHub + canonical Drive + `docs/automation/DEV4_*`.

## Evidence extension

### PROVEN_PRODUCT_DEFECT — PGN export filesystem indirection is not fail-closed

The previously proven direct symlink-parent escape is now covered as a broader external-path boundary defect. `save_pgn_atomic()` performs no symlink/reparse-chain validation before using `destination.parent` for `NamedTemporaryFile` and `destination` for `os.replace()`.

Strict regression `tests/test_dev4_pgn_export_path_security.py` now covers three cases:

1. direct symlink/reparse parent causing the write to land in another directory;
2. a deeper symlink/reparse ancestor above a real direct parent, preventing a superficial parent-only check from producing false GREEN;
3. an existing symlink destination in `overwrite=True`, which current code accepts and can replace as an indirection object instead of refusing the submitted path.

Product source is intentionally unchanged. The gate requires fail-closed rejection before any mutation through filesystem indirection.

QA evidence commit:
- `5715b167500bb88287c41f1354f20d05c0fd29a1` — `test(security): extend PGN export path-indirection gate`.

## Previously locked defects

1. Import/ChessBase symlink/reparse indirection is followed instead of failing closed.
2. PGN import uses an unbounded full-text `handle.read()` after bounded hashing.
3. ChessBase serialized probe/integrity/manifest payloads expose absolute local paths.
4. PGN `expected_sha256` optimistic-concurrency commit race can overwrite newer content.
5. PGN `overwrite=False` commit race can clobber a destination created after preflight.
6. PGN export path indirection is not fail-closed; direct parent, ancestor-chain and destination symlinks are now covered by strict QA evidence.

## Additional classifications

- INCONCLUSIVE: exact QA-head CI observability remains absent; absence is not GREEN.
- INCONCLUSIVE: parent-directory durability across crash/power loss is not promoted to Product defect without a stronger explicit durability contract and reproducible platform evidence.
- INCONCLUSIVE: generic `SourceFingerprint.path`, `BatchInspectionItem.path/error` and PGN exception path strings are not classified as user-visible leakage until a real UI/persistence/report sink is proven.
- HUMAN_ONLY: exact fresh Windows native-menu/NVDA usability. `NVDA_VERIFIED=NO`.

## Preserved findings / boundaries

- `docs/automation/DEV4_CHESSBASE_CAPABILITY_MATRIX.md` remains evidence-only and does not infer proprietary decoder compatibility from suffix recognition.
- PROVEN_PRODUCT_INTEGRATION_RISK: preserve accepted DEV1/integration `web/stage1_board_actions.js` semantics.
- PROVEN_RELEASE_PIPELINE_BLOCKER: `nuitka-compilation-report.xml` must remain CI evidence only and stay out of user ZIPs.
- No Ctrl+A/Ctrl+C Product defect claim.
- Windows strict WIP=1 respected.
- No force-push, DEV5/integration mutation, `tools/qa` or strict Windows workflow edit, DEV3 ACSDB performance takeover, frozen release merge or Windows candidate.

## Next action

Recheck final QA branch head and PR #67 Actions. Continue PGN temp-file/commit recovery (`fsync`, `os.replace`, cleanup, permissions, directory durability), then generic import size/encoding/cancellation limits and end-to-end path/error exposure tracing. Continue ChessBase unknown-version/resource-boundary evidence without inventing proprietary semantics. Re-enter Stage1 package work only through DEV5/Audit-authorized reconciliation.
