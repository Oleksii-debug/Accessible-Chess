# Canonical format capability matrix

Generated deterministically from `acs.format_capabilities.FORMAT_CAPABILITIES`.
Do not edit this table independently; change the typed authority and regenerate.

Status vocabulary: `SUPPORTED`, `PARTIAL`, `UNSUPPORTED`, `BLOCKED`.
`PARTIAL` and `BLOCKED` are product truth, not temporary aliases for support.

Operation meanings:
- **Read**: parse/import/adopt source semantics into a canonical product model.
- **Edit**: modify canonical semantic state through a supported product editing workflow; not source writeback.
- **Write**: serialize/export canonical semantic state to this interchange format; textual position formats may produce canonical text rather than a dedicated file-save command.
- **Round-trip**: read then write/reopen with the semantics stated by the boundary preserved.

| Format | Extensions | Read | Edit | Write | Round-trip | Availability | Boundary |
| --- | --- | --- | --- | --- | --- | --- | --- |
| FEN position | .fen | SUPPORTED | PARTIAL | SUPPORTED | PARTIAL | built_in | Read/write are built in and validated by the canonical chess core; current full-editor/corpus closure is still converging, so edit/round-trip remain PARTIAL. |
| EPD position interchange | .epd | SUPPORTED | PARTIAL | SUPPORTED | PARTIAL | built_in | Canonical position fields can be edited through PositionState; unknown operations remain opaque and operation editing/engine-command semantics are not claimed. |
| PGN / GameTree | .pgn | SUPPORTED | SUPPORTED | SUPPORTED | PARTIAL | built_in | Representable valid GameTree semantics round-trip; malformed recovery may canonicalize syntax and must surface warnings instead of fabricating chess state. |
| ACSDB Library database | .acsdb | PARTIAL | PARTIAL | PARTIAL | PARTIAL | built_in | Internal durable Library format; current open convergence/qualification work prevents a whole-product SUPPORTED closure claim. |
| Plain-text chess book | .txt | SUPPORTED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | built_in | Semantic import is supported; source-format editing/writeback is not claimed. |
| Markdown chess book | .md, .markdown | SUPPORTED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | built_in | Semantic import is supported; source-format editing/writeback is not claimed. |
| HTML chess book | .html, .htm | SUPPORTED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | built_in | Semantic import is supported; active content is not a chess authority and source-format writeback is not claimed. |
| EPUB chess book | .epub | SUPPORTED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | built_in | Semantic import is supported; source-format editing/writeback is not claimed. |
| ChessBase CBH family | .cbh | PARTIAL | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | optional_external_backend | Read is conditional on the pinned external backend and qualified Standard records. Chess960/Fischer Random remains UNSUPPORTED; no writeback. |
| ChessBase CBV archive | .cbv | PARTIAL | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | optional_external_backend | Read is conditional on both qualified external backends and the inherited CBH semantic boundary; no writeback. |
| Legacy ChessBase CBF/CBI pair | .cbf, .cbi | BLOCKED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | blocked_external_evidence | Blocked pending a lawful authentic same-stem fixture corpus, independent semantic oracle and qualified bounded decoder. |
| ChessBase 2CBH | .2cbh | BLOCKED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | blocked_external_evidence | No fixture-backed semantic decoder is qualified. |
| ChessBase 2CBV archive | .2cbv | BLOCKED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | blocked_external_evidence | Official archive-family identity and real paired-source evidence exist, but no qualified semantic decoder/publication path is integrated into the current product apex. |
| ChessBase CBONE | .cbone | BLOCKED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | blocked_external_evidence | No fixture-backed semantic decoder is qualified. |
| ChessBase CBZ encrypted archive | .cbz | BLOCKED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | blocked_external_evidence | Password/decryption lifecycle is not implemented; no silent password handling is allowed. |

## Authority rule

This matrix declares capabilities only. FEN/SAN/legality, GameTree, PGN,
Library publication and BookDocument semantics remain owned by their existing
canonical modules. Format adapters may validate syntax and bounded transport,
but they must not invent a legal move or publish a chess position rejected by
the canonical chess/application authority.

## ChessBase evidence relationship

`docs/automation/DEV4_CHESSBASE_CAPABILITY_MATRIX.md` remains the detailed
CBH/CBV/variant evidence source. `docs/automation/V2_CHESSBASE_CAPABILITIES.json`
remains the CBF/CBI evidence-only source. This whole-product matrix consumes
those boundaries; it does not replace or silently promote them.
