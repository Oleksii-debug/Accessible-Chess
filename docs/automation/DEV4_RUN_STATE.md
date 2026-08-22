# DEV4 RUN STATE

RUN_ID: 20260822-1604-full-product-qa
STATUS: COMPLETE
MODE: SAFE_OVERLAP_QA_EVIDENCE
ROLE: DEV4 independent QA/evidence/security

## Live snapshot

- DEV4 Product source: `manual5/dev4-platform-security-packaging-20260821@a4209d005ea0a1476f8eafb4822f4d39ac50ee5a`.
- Accepted integration: `manual5/integration-20260821@0fa442330bc2bb03636ff9297512da4c29e38684`.
- DEV5 reconciliation PR #66 remains separate and OPEN/DRAFT at `abff45ebcc4b5af2a85ab0c456b025b5098c6e29`; DEV4 did not mutate it.
- DEV4 QA branch: `qa/dev4-chessbase-symlink-security-20260822`.
- New strict evidence commit: `5a83ab0eb76455ad8e5ed63378acbfc08e02a462` — `test(qa): gate ChessBase integrity I/O observability`.
- QA PR #67 remains OPEN/DRAFT; metadata commits follow the evidence commit, so final exact branch head must be read live after synchronization.
- Exact pre-write QA head `bc72a86e16a55331a71d8d749d09870c1f018c6b` had no commit-associated Actions: `INCONCLUSIVE`, not GREEN.
- Windows strict WIP=1 untouched. `NVDA_VERIFIED=NO`.

## Evidence extension — ChessBase integrity re-verification leaks raw component I/O failures

`verify_integrity_snapshot()` promises family re-verification but delegates directly to `capture_integrity_snapshot()` / `_fingerprint()`. If an already-recorded companion becomes unreadable, a raw `PermissionError`/`OSError` escapes instead of a domain-level fail-closed verification failure. This extends locked defect class 9 from manifest verification onto the separate integrity-snapshot verification API.

Strict deterministic gate: `tests/test_dev4_chessbase_integrity_io_observability.py`. The gate accepts a domain `RuntimeError`-class verification failure but rejects raw filesystem `OSError` leakage. Product code intentionally unchanged.

## Locked PROVEN_PRODUCT_DEFECT findings

1. Import/ChessBase symlink-reparse indirection follows targets instead of failing closed.
2. PGN import lacks a bounded full-text/resource boundary and finite source cap.
3. ChessBase serialized probe/integrity/manifest DTOs expose absolute local paths.
4. PGN `expected_sha256` overwrite has a TOCTOU lost-update race.
5. PGN `overwrite=False` can clobber a destination created after preflight.
6. PGN export filesystem indirection is not fail-closed.
7. ChessBase companion-directory I/O failures collapse into ordinary no-companion evidence.
8. Generic import `inspect_batch()` aborts on importer `RuntimeError` instead of recording and continuing.
9. ChessBase verification I/O observability is not domain-safe: manifest verification and integrity re-verification can propagate raw hash/open filesystem failures.
10. Shared import fingerprinting can open FIFO/special files before fail-closed type validation.
11. Provenance hashing is not a stable snapshot: shared import fingerprint and ChessBase integrity fingerprint both accept in-flight same-size mutation.
12. ACSDB failed-import history persists raw exception text and exposes it through `ImportHistoryService`.

## Other classifications

- QA EVIDENCE: PGN export recovery/temp cleanup/POSIX temp privacy.
- QA EVIDENCE: release-facing Stockfish provider path errors are sanitized.
- INCONCLUSIVE: exact QA-head CI until checks appear.
- INCONCLUSIVE: PGN parent-directory crash/power-loss durability.
- HUMAN_ONLY: exact fresh Windows/NVDA usability.
- No Ctrl+A/Ctrl+C Product defect claim.

## Next action

Recheck PR #67 final exact head and Actions. Continue generic import cancellation/encoding/truncation/duplicate-source recovery and concrete persisted/UI/report error-sink tracing. Preserve ChessBase verification observability gates without inventing proprietary decoder semantics. Stay in SAFE OVERLAP and out of Windows strict/Product-owner lanes.
