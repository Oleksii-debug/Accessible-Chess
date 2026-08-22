# DEV4 RUN STATE

RUN_ID: 20260822-1400-full-product-qa
STATUS: COMPLETE
MODE: SAFE_OVERLAP_QA_EVIDENCE
ROLE: DEV4 independent QA/evidence/security

## Live snapshot

- DEV4 Product source: `manual5/dev4-platform-security-packaging-20260821@a4209d005ea0a1476f8eafb4822f4d39ac50ee5a`.
- Accepted integration: `manual5/integration-20260821@0fa442330bc2bb03636ff9297512da4c29e38684` (live compare IDENTICAL).
- DEV4 QA branch: `qa/dev4-chessbase-symlink-security-20260822`.
- New strict evidence commit: `55e0ab813d07ed6ea9e7b350a9cc899b5616a15c` — `test(security): gate unstable import fingerprints`.
- QA PR #67 remains OPEN/DRAFT/MERGEABLE; metadata commits follow the evidence commit.
- `AGENTS.md` and shared `docs/codex/{CURRENT_STATE,NEXT_WORK,SESSION_HANDOFF}.md` remain absent on the inspected QA ref.
- Windows strict WIP=1 untouched. `NVDA_VERIFIED=NO`.

## New PROVEN_PRODUCT_DEFECT — provenance fingerprint is not a stable snapshot

`acs.import_contract.fingerprint()` hashes a source stream and then records a later `stat()`, but it does not prove that the source remained unchanged while hashing. A same-size concurrent write can occur inside the digest loop and the function still returns a normal `SourceFingerprint`, allowing stale or mixed bytes to be represented as valid provenance evidence.

Strict deterministic gate: `tests/test_dev4_import_fingerprint_atomicity.py`. The test mutates an equal-size source immediately after the first digest update and requires the fingerprint operation to fail closed. Product code intentionally unchanged.

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
11. Shared import fingerprinting can return provenance while the source mutates during hashing instead of rejecting the unstable snapshot.

## Other classifications

- QA EVIDENCE: PGN export recovery/temp cleanup and POSIX temp privacy.
- QA EVIDENCE: release-facing Stockfish provider path errors are sanitized.
- INCONCLUSIVE: exact QA-head CI until checks appear.
- INCONCLUSIVE: PGN parent-directory crash/power-loss durability.
- INCONCLUSIVE: generic path/error strings reaching real UI/persisted sinks beyond proven ChessBase DTO leakage.
- HUMAN_ONLY: exact fresh Windows/NVDA usability.
- No Ctrl+A/Ctrl+C Product defect claim.

## Next action

Recheck PR #67 exact head and Actions. Continue generic import cancellation/encoding/truncation evidence and ChessBase component snapshot/open/stat/hash observability. Promote leakage only with concrete persisted/UI/report sink evidence. Stay in SAFE OVERLAP and out of Windows strict/Product-owner lanes.
