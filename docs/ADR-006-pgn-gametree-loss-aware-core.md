# ADR-006: Loss-aware PGN/GameTree ownership and recovery

Status: accepted for isolated Core-forward work.

Base before this sprint: `805b1a6dcbbcbdcd1a7b9a0c661e39a3a0e52dd9` on `feature/core-forward-foundation`.

## Decision

`acs.gametree` remains the single structural source of truth for PGN games and recursive variations. This sprint expands that model rather than creating a second parser/tree.

The subsystem owns:

- multi-game PGN collection splitting;
- arbitrary tags plus canonical ordering of the Seven Tag Roster, SetUp/FEN and extension tags on export;
- comments, numeric and symbolic NAGs, recursive RAV/sub-RAV structure and results;
- structural preservation of SAN tokens including castling, captures, promotions, check/mate, en-passant notation extensions and null/unsupported move tokens without reimplementing chess legality;
- deterministic canonical serialization;
- recovery-oriented malformed-source diagnostics and preservation of unsupported tokens where safe;
- PGN escape-line preservation;
- recursive traversal and stable semantic structural signatures for round-trip/corpus tests.

`acs.pgn_semantics` owns the typed metadata/setup/result/diagnostic projection consumed by storage/UI adapters. Parser diagnostics are projected by stable parser codes rather than by parsing human warning strings where structured evidence is available.

Existing `acs.game_references` remains the neutral Game/Variation/Move/Position reference boundary. No second board/FEN/history model is introduced.

## Non-goals and boundaries

- Chess legality, SAN legality, side-to-move and exact position mutation remain canonical chess-core responsibilities.
- `SetUp`/`FEN` metadata semantics are projected here, but board-level FEN legality is not reimplemented.
- SQLite repositories remain outside this module.
- Proprietary ChessBase CBH/CBV/CBF decoding is not guessed here.
- Windows/UI/NVDA/package behavior is outside this isolated branch.

## Recovery policy

Malformed input must not be silently normalized into invented chess meaning. Recoverable structure is retained, typed diagnostics are emitted, and unsupported tokens are preserved where possible. Canonical export may normalize whitespace, tag order, semicolon comments to brace comments, and attached symbolic NAG spelling into explicit structural NAGs; semantic content and tree identity must remain stable after canonicalization.

## Verification

The regression corpus covers nested variations/subvariations, comments, numeric and symbolic NAGs, multi-game input, tag escaping, SetUp/FEN, result mismatch, malformed comments/RAVs/parentheses/NAGs, unsupported trailing content, special SAN forms and a synthetic 1,000-game collection with deterministic reparse/export.