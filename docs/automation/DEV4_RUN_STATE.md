# DEV4 RUN STATE

RUN_ID: 20260822-1200-full-product-qa
STATUS: COMPLETE
MODE: SAFE_OVERLAP_QA_EVIDENCE
ROLE: DEV4 independent QA/evidence/security

## Live snapshot

- DEV4 Product source remains `manual5/dev4-platform-security-packaging-20260821@a4209d005ea0a1476f8eafb4822f4d39ac50ee5a`.
- Accepted integration remains `manual5/integration-20260821@0fa442330bc2bb03636ff9297512da4c29e38684`; its earlier GREEN gates apply only to that exact SHA.
- DEV5 reconciliation PR #66 remains OPEN/DRAFT at `abff45ebcc4b5af2a85ab0c456b025b5098c6e29`.
- SAFE OVERLAP remains mandatory; no DEV5/integration/DEV2/DEV3 Product mutation was performed by DEV4.
- DEV4 QA branch: `qa/dev4-chessbase-symlink-security-20260822`.
- New evidence commit: `0f911daefd131f7eee1a6365c893e56c365eb1e5` — `test(qa): gate ChessBase manifest I/O observability`.
- QA PR #67 remains OPEN/DRAFT/MERGEABLE.
- Exact evidence-head Actions were absent at inspection; absence is `INCONCLUSIVE`, never GREEN.
- `AGENTS.md` and shared `docs/codex/{CURRENT_STATE,NEXT_WORK,SESSION_HANDOFF}.md` remain absent on inspected refs.
- Windows strict WIP=1 untouched. `NVDA_VERIFIED=NO`.

## New PROVEN_PRODUCT_DEFECT — manifest verification I/O observability

`verify_manifest_unchanged()` is a public verification boundary returning `(ok, problems)` and explicitly records missing/size/hash discrepancies. However, an I/O failure while re-hashing an evidence file is not converted into a negative verification result: `_hash_file()` raises `OSError`/`PermissionError` through the public API. The caller therefore loses structured verification evidence instead of receiving `ok=False` plus an explicit unavailable/read-failure problem.

Strict deterministic gate: `tests/test_dev4_chessbase_manifest_io_observability.py`, which injects a `PermissionError` at the hash boundary and requires failed verification with explicit I/O-unavailable evidence. Product code intentionally unchanged.

## Locked PROVEN_PRODUCT_DEFECT findings

1. Import/ChessBase symlink-reparse indirection follows targets instead of failing closed.
2. PGN import lacks a bounded full-text/resource boundary and finite source cap.
3. ChessBase serialized probe/integrity/manifest DTOs expose absolute local paths.
4. PGN `expected_sha256` overwrite has a TOCTOU lost-update race.
5. PGN `overwrite=False` can clobber a destination created after preflight.
6. PGN export filesystem indirection is not fail-closed.
7. ChessBase companion-directory I/O failures collapse into ordinary no-companion evidence.
8. Generic import `inspect_batch()` aborts on importer `RuntimeError` instead of recording and continuing.
9. ChessBase manifest re-verification propagates hash/open I/O failure instead of returning explicit failed verification evidence.

## Other classifications

- QA EVIDENCE: PGN export recovery/temp cleanup and POSIX temp privacy.
- QA EVIDENCE: release-facing Stockfish provider path errors are sanitized.
- INCONCLUSIVE: exact QA-head CI until checks appear.
- INCONCLUSIVE: PGN parent-directory crash/power-loss durability.
- INCONCLUSIVE: generic path/error strings reaching real UI/persisted sinks beyond already-proven ChessBase DTO leakage.
- HUMAN_ONLY: exact fresh Windows/NVDA usability.
- No Ctrl+A/Ctrl+C Product defect claim.

## Next action

Recheck PR #67 final metadata head and Actions. Continue generic import resource/cancellation evidence and ChessBase component open/stat/hash observability, then trace only concrete user-facing/persisted error sinks. Remain in SAFE OVERLAP and do not enter Windows strict/Product-owner lanes.
