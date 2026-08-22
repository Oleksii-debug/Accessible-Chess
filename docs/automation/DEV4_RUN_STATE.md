# DEV4 RUN STATE

RUN_ID: 20260822-1503-full-product-qa
STATUS: COMPLETE
MODE: SAFE_OVERLAP_QA_EVIDENCE
ROLE: DEV4 independent QA/evidence/security

## Live snapshot

- DEV4 Product source: `manual5/dev4-platform-security-packaging-20260821@a4209d005ea0a1476f8eafb4822f4d39ac50ee5a`.
- Accepted integration: `manual5/integration-20260821@0fa442330bc2bb03636ff9297512da4c29e38684` (live compare IDENTICAL at run start).
- DEV5 reconciliation PR #66 remains separate and OPEN/DRAFT at `abff45ebcc4b5af2a85ab0c456b025b5098c6e29`; DEV4 did not mutate it.
- DEV4 QA branch: `qa/dev4-chessbase-symlink-security-20260822`.
- New strict evidence commit: `97044de22bbab7098f0ba6a06fd9dfa5cd37562f` — `test(security): gate unstable ChessBase integrity snapshots`.
- QA PR #67 remains OPEN/DRAFT; metadata commits follow the evidence commit, so final exact branch head must be read live after synchronization.
- Windows strict WIP=1 untouched. `NVDA_VERIFIED=NO`.

## Evidence extension — ChessBase integrity snapshots are not atomic

`acs.chessbase_integrity._fingerprint()` hashes a source in chunks but performs no pre/post identity/stat check around the read. A same-size concurrent mutation can therefore produce normal `SourceFileEvidence` representing mixed/stale bytes rather than one stable source state. This extends the already locked provenance-atomicity defect for shared `acs.import_contract.fingerprint()` onto the separate ChessBase integrity path.

Strict deterministic gate: `tests/test_dev4_chessbase_integrity_atomicity.py`. Product code intentionally unchanged.

## Locked PROVEN_PRODUCT_DEFECT findings

1. Import/ChessBase symlink-reparse indirection follows targets instead of failing closed.
2. PGN import lacks a bounded full-text/resource boundary and finite source cap.
3. ChessBase serialized probe/integrity/manifest DTOs expose absolute local paths.
4. PGN `expected_sha256` overwrite has a TOCTOU lost-update race.
5. PGN `overwrite=False` can clobber a destination created after preflight.
6. PGN export filesystem indirection is not fail-closed.
7. ChessBase companion-directory I/O failures collapse into ordinary no-companion evidence.
8. Generic import `inspect_batch()` aborts on importer `RuntimeError` instead of recording and continuing.
9. ChessBase manifest re-verification propagates hash/open I/O failure instead of returning explicit failed-verification evidence.
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

Recheck PR #67 final exact head and Actions. Continue generic import cancellation/encoding/truncation evidence and ChessBase component open/stat/hash I/O observability. Trace further errors only into concrete persisted/UI/report sinks. Stay in SAFE OVERLAP and out of Windows strict/Product-owner lanes.
