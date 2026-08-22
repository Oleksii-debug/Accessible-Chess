# DEV4 RUN STATE

RUN_ID: 20260822-0308-full-product-qa
STATUS: COMPLETE
MODE: SAFE_OVERLAP_QA_EVIDENCE
ROLE: DEV4 independent QA/evidence/security

## Live snapshot

- DEV4 Stage1 Product source: `manual5/dev4-platform-security-packaging-20260821` @ `a4209d005ea0a1476f8eafb4822f4d39ac50ee5a`.
- Manual5 integration: `manual5/integration-20260821` @ `0fa442330bc2bb03636ff9297512da4c29e38684`.
- Exact integration CI remains UI Semantic Gate `32532577650` SUCCESS and Stage1 Saturation `32532577641` SUCCESS.
- DEV5 reconciliation draft PR #66 remains open/draft at `abff45ebcc4b5af2a85ab0c456b025b5098c6e29` with UI Semantic Gate `32532415239` SUCCESS and Stage1 Saturation `32532415296` SUCCESS.
- DEV4 QA branch: `qa/dev4-chessbase-symlink-security-20260822`.
- New QA evidence commit: `262ba68f4a5845335f463df7b8b67dcd7b6adb1a` — `test(security): gate PGN atomic lost-update race`.
- DEV4 QA draft PR #67 remains open/draft.
- Exact QA evidence commit Actions: none observed. Classification: INCONCLUSIVE CI observability, not GREEN.
- Requested `AGENTS.md` and `docs/codex/{CURRENT_STATE,NEXT_WORK,SESSION_HANDOFF}.md` are absent on the checked repository ref.
- Windows strict WIP=1 remains untouched. `NVDA_VERIFIED=NO`.

## Findings

### PROVEN_PRODUCT_DEFECT — external import symlink/reparse fail-closed boundary

Shared import/ChessBase provenance follows filesystem indirection rather than rejecting it. Strict QA gate: `tests/test_dev4_chessbase_symlink_security.py`.

### PROVEN_PRODUCT_DEFECT — PGN unbounded read/resource-exhaustion boundary

`acs.pgn_service._read_text_snapshot()` performs a full unbounded `handle.read()` after bounded hashing, with no explicit source-size cap or streaming parser boundary. Strict QA gate: `tests/test_dev4_pgn_resource_security.py`.

### PROVEN_PRODUCT_DEFECT — private local paths serialized into ChessBase report/provenance DTOs

Probe, integrity snapshot and bundle manifest report payloads serialize absolute/local source paths. Strict QA gate: `tests/test_dev4_chessbase_report_path_privacy.py`.

### PROVEN_PRODUCT_DEFECT — PGN optimistic overwrite TOCTOU can lose a newer writer

`save_pgn_atomic()` checks `expected_sha256` before serializing/writing the temporary file, then commits with unconditional `os.replace()` and does not revalidate the destination at the commit boundary. A writer that changes the destination after the preflight hash but before replacement is silently overwritten, despite the public contract saying `expected_sha256` refuses newer edits.

DEV4 reproduced the state transition independently: original hash matches at preflight, a concurrent writer changes the destination immediately before replace, and the current algorithm replaces that newer content with the stale save. Strict deterministic QA gate: `tests/test_dev4_pgn_export_concurrency_security.py`. It injects the competing write at the atomic replacement boundary and requires `PgnConcurrentWriteError` plus preservation of the concurrent content. Product code is intentionally unchanged.

### Evidence artifact — ChessBase capability matrix

`docs/automation/DEV4_CHESSBASE_CAPABILITY_MATRIX.md` continues to separate suffix recognition/provenance from proprietary decoder compatibility.

## Preserved findings / boundaries

- PROVEN_PRODUCT_INTEGRATION_RISK: preserve accepted DEV1/integration `web/stage1_board_actions.js` semantics during any Stage1 reconciliation.
- PROVEN_RELEASE_PIPELINE_BLOCKER: `nuitka-compilation-report.xml` may be CI diagnostic evidence only and must not ship in a user ZIP.
- HUMAN_ONLY: exact fresh Windows native-menu/NVDA usability. `NVDA_VERIFIED=NO`.
- No Product Ctrl+A/Ctrl+C defect is claimed.
- No force-push, DEV5/integration mutation, `tools/qa` or strict Windows workflow edit, frozen-release merge, Windows candidate creation, or DEV3 ACSDB performance takeover occurred.

## Evidence discipline

The existing integration/DEV5 GREEN runs do not execute or validate the new QA-only external-format assertions. QA PR #67 has no observed commit-associated Actions for the new evidence commit, so CI remains INCONCLUSIVE rather than inferred GREEN. The PGN race finding is based on the live implementation's check-then-replace ordering, its explicit optimistic-concurrency contract, an independently reproduced race state transition, and a strict deterministic regression.

## Next action

1. Recheck PR #67 exact-head Actions without treating absence as GREEN.
2. Audit PGN export failure recovery further: parent/destination indirection, temp cleanup/permissions, replacement/fsync failure, directory durability, deterministic serialization and path/error leakage.
3. Continue generic import resource audit: explicit source caps, encoding abuse, truncation, cancellation/recovery and duplicate-source behavior.
4. Trace `SourceFingerprint.path`, `BatchInspectionItem.path/error` and PGN exceptions into actual persisted/UI/report surfaces; classify only proven exposure.
5. Continue ChessBase unknown-version/resource-limit evidence without inventing proprietary decoder semantics.
6. Re-enter Stage1 package/security only through DEV5/Audit-authorized reconciliation and verify future user ZIP excludes `nuitka-compilation-report.xml`.
