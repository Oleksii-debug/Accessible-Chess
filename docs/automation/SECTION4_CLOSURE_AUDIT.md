# Section 4 Closure Audit — ChessBase family

Canonical Section-plan scope: Section 4 — ChessBase family: CBH, CBV, CBF and related formats.

Base authority for this closure lineage: terminal Section-3 integration `ca543281040b9030d47abbbb244fb592ae63110d`.

## Acceptance mapping

- 4.1 Capability matrix: `acs.format_capabilities.FORMAT_CAPABILITIES` and the existing ChessBase evidence matrices keep CBH/CBV PARTIAL/read-only through an optional external backend and keep CBF/CBI, 2CBH, 2CBV, 2CBZ, CBONE and CBZ BLOCKED/UNSUPPORTED where no qualified semantic decoder exists.
- 4.2 Read-only adapters: existing `acs.chessbase_decoder`, CBV extraction and `ChessBaseLibraryImportService` publish only canonical GameTree/metadata/provenance into ACSDB/PGN-facing authorities. Proprietary source files are never a chess-rules authority.
- 4.3 Variations/comments/metadata/positions/damaged-partial input: existing decoder/import tests cover nested variations, comments/NAGs, metadata, source indexes, warnings, damaged/unsupported records and stable ImportReport behavior.
- 4.4 Honest unsupported semantics: explicit Chess960/Fischer Random records fail closed per record; unsupported families remain blocked; malformed or unrepresentable decoded games fail before publication.
- 4.5 Lawful authentic evidence: the pinned open-source libcbh corpus at commit `9641c5c3949d8fb210b17dd9aa54455645843696` supplies an authentic mixed Standard/Chess960 CBH family and independent PGN reference. Missing lawful proprietary fixtures for blocked families remain external evidence gaps and do not promote support.

## One-authority invariants

The ChessBase bridge is transport/decoding only. Canonical Board/GameTree serialization validates accepted state. Backend SetUp/FEN cannot override canonical start-position truth. No ChessBase adapter implements independent legality. Optional backend binaries are not shipped in the default source tree.

## Closure qualification

The dedicated `section4-chessbase-closure.yml` gate executes:
1. dual-OS capability/decoder/import/integrity/cancellation/CBV/GameTree/Library regressions;
2. canonical format-capability validation and core selftest;
3. Ubuntu pinned real libcbh mixed Standard/Chess960 corpus build and import;
4. source-tree check that optional backend binaries are not introduced.

DONE is forbidden until exact-head available qualification has no known acceptance failure, the candidate is integrated, and post-integration readback is recorded in `SEQUENTIAL_CLOSURE_STATE.md`.

Blocked proprietary families are not silently upgraded by this Section closure.
