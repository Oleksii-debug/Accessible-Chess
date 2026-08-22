# DEV4 RUN STATE

RUN_ID: 20260822-0600-full-product-qa
STATUS: COMPLETE
MODE: SAFE_OVERLAP_QA_EVIDENCE
ROLE: DEV4 independent QA/evidence/security

## Live snapshot

- DEV4 Stage1 Product source: `manual5/dev4-platform-security-packaging-20260821` @ `a4209d005ea0a1476f8eafb4822f4d39ac50ee5a`.
- Manual5 integration: `manual5/integration-20260821` @ `0fa442330bc2bb03636ff9297512da4c29e38684`; live compare against that SHA is IDENTICAL.
- Integration exact CI remains UI Semantic Gate `32532577650` SUCCESS and Stage1 Saturation `32532577641` SUCCESS.
- DEV5 reconciliation draft PR #66 remains open/draft at `abff45ebcc4b5af2a85ab0c456b025b5098c6e29`; DEV4 did not touch that owner lane.
- DEV4 QA branch: `qa/dev4-chessbase-symlink-security-20260822`.
- New QA evidence commit: `5715b167500bb88287c41f1354f20d05c0fd29a1` — `test(security): extend PGN export path-indirection gate`.
- DEV4 QA draft PR #67 remains open/draft.
- Commit-associated Actions for the exact QA evidence head are unobserved. Classification: INCONCLUSIVE CI observability, not GREEN.
- Requested `AGENTS.md` and `docs/codex/CURRENT_STATE.md` remain absent on the checked QA ref; repository search also did not surface `docs/codex/NEXT_WORK.md` or `docs/codex/SESSION_HANDOFF.md`. Operative technical state is live GitHub + canonical Drive + `docs/automation/DEV4_*`.
- Windows strict WIP=1 remains untouched. `NVDA_VERIFIED=NO`.

## New evidence extension — PGN export filesystem indirection

The existing PROVEN_PRODUCT_DEFECT class is broader than a direct symlink parent. `save_pgn_atomic()` has no fail-closed path-indirection validation before temp creation or commit. The strict QA gate now covers:

1. direct symlink/reparse parent (`submitted/exports -> external`);
2. a symlink/reparse ancestor above a real direct parent (`submitted/linked/nested/out.pgn`);
3. an existing symlink destination accepted in `overwrite=True`, where current `os.replace()` semantics can replace the indirection object instead of rejecting the submitted path.

Strict gate: `tests/test_dev4_pgn_export_path_security.py`.
Product source is intentionally unchanged; assertions are not weakened for GREEN.

## Locked findings

### PROVEN_PRODUCT_DEFECT
- External import/ChessBase symlink-reparse indirection follows filesystem targets instead of failing closed.
- PGN import performs an unbounded full-text `handle.read()` after bounded hashing.
- Serialized ChessBase probe/integrity/manifest DTOs expose absolute/local paths.
- PGN `expected_sha256` optimistic overwrite has a TOCTOU lost-update window.
- PGN `overwrite=False` can clobber a destination created after preflight.
- PGN export path handling accepts filesystem indirection instead of failing closed; strict coverage now includes direct parent, deeper ancestor and destination-file symlinks.

### INCONCLUSIVE
- QA PR #67 exact-head CI observability: no commit-associated Actions observed.
- PGN directory-entry durability across power loss remains unproven; file `fsync` exists, but no parent-directory durability claim is made without stronger platform contract/evidence.
- Generic `SourceFingerprint.path`, `BatchInspectionItem.path/error` and PGN exception path leakage into actual UI/persisted surfaces remains unproven beyond the already-proven ChessBase serialized DTO leakage.

### HUMAN_ONLY
- Exact fresh Windows native-menu/NVDA usability. `NVDA_VERIFIED=NO`.

## Preserved boundaries

- PROVEN_PRODUCT_INTEGRATION_RISK: preserve accepted DEV1/integration `web/stage1_board_actions.js` semantics during any Stage1 reconciliation.
- PROVEN_RELEASE_PIPELINE_BLOCKER: `nuitka-compilation-report.xml` may remain separate CI evidence only and must not ship in a user ZIP.
- No Product Ctrl+A/Ctrl+C defect is claimed.
- No force-push, DEV5/integration mutation, `tools/qa` or strict Windows workflow edit, frozen-release merge, Windows candidate creation, or DEV3 ACSDB performance takeover occurred.

## Next action

1. Recheck PR #67 exact-head Actions without treating absence as GREEN.
2. Audit PGN temp/commit recovery: temp permissions/cleanup, `os.replace` failure, `fsync` failure and platform-specific directory durability.
3. Continue generic import resource limits: explicit size caps, huge/truncated content, encoding abuse, duplicate sources, cancellation and recovery.
4. Trace generic provenance/error paths into actual persisted/UI/report surfaces and classify only direct evidence.
5. Continue ChessBase unknown-version/resource-boundary evidence without inventing proprietary decoder semantics.
6. Re-enter Stage1 package/security only through DEV5/Audit-authorized reconciliation and verify any future user ZIP excludes `nuitka-compilation-report.xml`.
