# Section 0 format authority and boundary contract

Status: executable contract for Section 0.1, 0.2 and 0.4.  
Source apex for this convergence pass: PR #2326 at `5854b528fbd3632cfa69553a70973123eaf14b54`.

This document records existing runtime authority. It does not introduce another parser, rules engine, database model, or provenance store. Live GitHub remains authoritative if the source apex moves.

## Canonical authority map

| Concern | Canonical authority | Format-side rule |
| --- | --- | --- |
| Legal chess position, legal moves, SAN production/parsing, playable FEN | `acs.chesscore.Board` and `acs.chesscore.Move` | Adapters must delegate chess legality instead of implementing parallel rules. |
| Editable/interchange position DTO | `acs.position_editor.PositionState` | Structural position interchange may use this immutable DTO; gameplay legality still belongs to `Board`. |
| EPD | `acs.epd` over `PositionState` | EPD owns interchange grammar and opaque operations only. It must not become a chess-rules engine. |
| PGN/GameTree structure | `acs.gametree.PgnGame`, `VariationLine`, `MoveNode` | Format readers/writers preserve canonical GameTree structure rather than inventing a second game model. |
| Strict editable PGN persistence | `acs.pgn_roundtrip` over the exact `acs.gametree` types/functions | Recovery-tolerant inspection and strict edit/write semantics remain distinct. Strict persistence fails closed when recovery would be required. |
| Stable game semantic identity | `acs.game_identity` over canonical `PgnGame` | Tree/record identity is versioned and independent of source/provenance metadata. |
| Library publication | `acs.library_import_service` -> ACSDB | Library accepts already-canonical `PgnGame` values and does not become a PGN parser. |
| Source provenance | Library/source records and adapter import evidence | Provenance stays outside `GameIdentity`; source identity must not alter chess/document identity. |

## Application boundary

The dependency direction for format ingestion is:

`untrusted format bytes/text -> bounded format adapter -> canonical PositionState or PgnGame/GameTree -> canonical chess validation where required -> Library/ACSDB publication`

The reverse direction for export is:

`canonical Position/GameTree -> format serializer -> atomic publication adapter`

A format adapter may validate its own lexical/container grammar and resource limits. It must not duplicate legal-move generation, SAN authority, playable-position rules, GameTree semantics, or Library persistence rules.

Malformed or partial input must remain observational until it is represented by a canonical object that passes the boundary required by that operation. A parser warning is not permission to publish a guessed legal position.

## Convergence record

This contract is stacked on the current composed formats apex #2326 rather than reopening older format implementations. The contract preserves the existing authorities above and adds only documentation, executable architecture tests, and a qualification workflow.

Historical branches and PRs remain evidence, not competing runtime authorities. New work must follow REUSE -> REPAIR -> CONVERGE -> QUALIFY -> INTEGRATE and must late-bind the live apex before integration.

Section 0.3 capability-state ownership is intentionally separate and currently active in another worker lane. This contract does not define or overwrite that matrix.

Section 0.5 ImportReport completeness is also not declared DONE by this file. Its exact residuals must be verified independently before Section 0 can close.

## Executable invariants

`tests/test_section0_format_authority_contract.py` verifies that:

- EPD uses the exact canonical `PositionState` and delegates FEN construction to `PositionState.from_fen`;
- strict PGN reuses the exact canonical GameTree classes/parser/serializer;
- Library and game identity consume the same canonical `PgnGame` class;
- source index/provenance does not alter versioned GameTree/record identity;
- canonical `Board` produces exact `Move` and SAN for legal move ingress;
- malformed strict PGN and malformed EPD fail without replacing an already-created canonical object.

The dedicated workflow also pins the exact inherited authority blobs and requires the delta to contain only this document, its test, and its workflow.

HUMAN_TESTED=NO  
NVDA_VERIFIED=NO
