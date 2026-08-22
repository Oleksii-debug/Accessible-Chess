# DEV4 RUN STATE

RUN_ID: 20260822-1300-full-product-qa
STATUS: COMPLETE
MODE: SAFE_OVERLAP_QA_EVIDENCE
ROLE: DEV4 independent QA/evidence/security

## Live snapshot

- DEV4 Product source remains `manual5/dev4-platform-security-packaging-20260821@a4209d005ea0a1476f8eafb4822f4d39ac50ee5a`.
- Accepted integration remains `manual5/integration-20260821@0fa442330bc2bb03636ff9297512da4c29e38684`.
- DEV5 reconciliation PR #66 remains OPEN/DRAFT at `abff45ebcc4b5af2a85ab0c456b025b5098c6e29`.
- DEV4 QA branch: `qa/dev4-chessbase-symlink-security-20260822`.
- New evidence commit: `cf61bbf18f352522ae3333deaff1e2dc353475b1` — `test(security): reject special-file import sources`.
- QA PR #67 remains OPEN/DRAFT/MERGEABLE.
- Previous exact QA-head Actions remained absent; absence is `INCONCLUSIVE`, never GREEN.
- `AGENTS.md` and shared `docs/codex/{CURRENT_STATE,NEXT_WORK,SESSION_HANDOFF}.md` remain absent on inspected refs.
- Windows strict WIP=1 untouched. `NVDA_VERIFIED=NO`.

## New PROVEN_PRODUCT_DEFECT — non-regular import source is opened before type validation

Shared `acs.import_contract.fingerprint()` opens a submitted path before establishing that it is a regular file. On POSIX this means a FIFO can block indefinitely waiting for a writer, and other special/device-like filesystem objects can trigger unintended I/O instead of being rejected at the external import boundary.

Strict deterministic gate: `tests/test_dev4_import_special_file_security.py`. The test creates a FIFO but patches the payload open so the QA run cannot hang; a safe implementation must reject the non-regular source before attempting the open. Product code intentionally unchanged.

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
10. Shared import fingerprinting can open FIFO/special files before fail-closed type validation.

## Other classifications

- QA EVIDENCE: PGN export recovery/temp cleanup and POSIX temp privacy.
- QA EVIDENCE: release-facing Stockfish provider path errors are sanitized.
- INCONCLUSIVE: exact QA-head CI until checks appear.
- INCONCLUSIVE: PGN parent-directory crash/power-loss durability.
- INCONCLUSIVE: generic path/error strings reaching real UI/persisted sinks beyond already-proven ChessBase DTO leakage.
- HUMAN_ONLY: exact fresh Windows/NVDA usability.
- No Ctrl+A/Ctrl+C Product defect claim.

## Next action

Recheck PR #67 final head/Actions. Continue generic import huge/truncated/encoding/cancellation/recovery evidence, then ChessBase component open/stat/hash observability and only concrete persisted/UI/report error sinks. Stay in SAFE OVERLAP; do not enter Windows strict or Product-owner lanes.
