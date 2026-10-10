# Section 55 — Evidenced 2015 UKAAF chess-Braille rule profile

Status: **PARTIAL, NOT DONE.** Scope: UKAAF (British) 2015 code for chess position representation. No language-wide certification, embossed page acceptance or chess notation formatter is claimed.

## Primary rule source

UKAAF, *Braille Chess Code and Layout* (2015), accessible through the British Braille Chess Association:
https://braillechess.org.uk/wp-content/uploads/2023/08/Braille-Chess-Notation.htm

Reference scope:
- Section 2.1 identifies pieces in British Braille chess notation, including the king, queen, rook, bishop, knight, and pawn.
- Section 3 specifies algebraic/descriptive game notation, numbers, disambiguation, capture, check, promotion, castling, commentary and game-analysis conventions. **A narrow lexical subset of clauses 3.2–3.6 and checkmate in 2.2 is implemented**: ordinary SAN-like piece/pawn destinations, pawn captures, piece disambiguation, checks and mate. Lexical conversion DOES NOT establish chess move legality or complete game-score translation; castling, promotions, annotated moves and full legal variation trees are rejected until independently qualified.
- Section 4 prescribes formatting for game, analysis, and move paragraphs, including special indentation. This is NOT fully implemented.
- Section 5.1 specifies Forsyth position glyphs with six-dot piece signs, dot 6 for black figures, lower numeric cells for empty squares and consolidation of consecutive empty ranks. This specific part is implemented as an independently reversible **position-cell serializer** in acs/chess_braille_ukaaf2015.py.
- Section 5.2 mandates textual label/indentation for diagrams (starts in cell 7), which the current generic PEF paginater DOES NOT implement. Section 6 prescribes chess-problem layout, also NOT implemented.

The published initial-position example in section 5.1 is used as an independent regression fixture under tests/test_section55_ukaaf2015_chess.py; it checks full starting board including 32 grouped empty squares. This is one positive fixture only, not comprehensive external certification.

UKAAF copyright belongs to its rights holder. The project derives a minimal technical representation and maintains a source citation; it does not copy or redistribute the full manual.

## Important source distinction: Liblouis en-chess.ctb is NOT the same profile

Liblouis's en-chess.ctb is a subtable mapping **Unicode chess figurines** to corresponding Braille figures; the published table uses dot 7 in white-piece representations. As a result, such cells are outside the current SIX-dot PEF/BRF profile and may not be silently truncated or recoded to UKAAF 2015. A separate explicit table/code and device profile must be chosen.

Liblouis reference: https://chromium.googlesource.com/external/liblouis/+/refs/heads/master/tables/en-chess.ctb
Liblouis documentation: https://github.com/liblouis/liblouis/blob/master/doc/liblouis.texi

UK RNIB explains that Braille chess has its own specialist code for moves and analysis, separate from ordinary literary transcription:
https://www.rnib.org.uk/living-with-sight-loss/education-and-learning/braille-tactile-codes/braille-codes/specialist-braille-codes-explained/

These are different contexts. Do NOT treat a generic literary Liblouis pass as automatically meeting the UKAAF chess-code requirements.

## Implemented acceptance evidence

- All input FEN is canonicalized by the **existing** acs.chesscore.Board; the exporter invents no chess rules or alternate FEN interpretation.
- Six-dot Unicode cells uniquely encode white pieces, black pieces and lower vacant-count digits. Groups of consecutive fully vacant ranks use their combined square count.
- Reverse reading of the generated Braille position expands to exactly 64 squares and must reproduce the original canonical FEN placement. Mismatches refuse emission.
- Fixed source example and synthetic adverse input are tested, including eight-dot injection, ambiguous separators, missing squares, unsupported characters and FEN failure.
- Each result explicitly reports UNVERIFIED_REQUIRES_DECISION, layout_qualified=false and tactile_qualified=false.

## Opt-in original-source UKAAF position catalog

Use --emit-ukaaf-diagrams in the local one-book CLI or the Boolean emit_ukaaf_diagrams in the bounded local queue. This option is available only when language is explicitly en or en-GB. The source must include at least one canonical semantic Position, Diagram or Exercise; plain text without a proven FEN fails closed.

The file chess-diagrams-ukaaf2015-unverified.json includes one record per canonical block with a FEN, UKAAF 2015 5.1 position cells and a reconstructed 64-square placement. It is labeled UNVERIFIED. The package report records its SHA-256, source edition and unqualified status. The independent verifier reimports the ORIGINAL book, re-renders every position and matches every byte of the catalog, even if an attacker also changes the catalog SHA field.

The catalog records six-dot positions only. It does not implement raised-paper tactile graphics, 5.2 cell-7 layout, BRF chess-layout encoding or professional print proof. A library operator must not treat it as an embossing instruction.

## Narrow algebraic move formatter

The pure encode_ukaaf2015_simple_san function covers examples from UKAAF 2015 3.2–3.6 (Rf4, d5, cxd5, Rxf4+, f5+, Nce5, Nb1c3) and the documented mate suffix. This lexical mapper is not a rules engine. It must only be called for SAN tokens independently proven legal by the existing canonical PGN/Board layer. It deliberately rejects castling, pawn promotion, annotation NAG, descriptive notation, numbered game records and punctuation variants pending fuller professional qualification.

## Canonical PGN legality bridge — narrow mainline only

The encode_ukaaf2015_canonical_mainline_pgn(pgn) function now accepts one bounded, warning-free game through the existing STRICT parse_pgn_text boundary, then applies every move through chesscore.Board.push_text and codes the **Board-generated canonical SAN** using the limited lexical UKAAF mapper. It records before/after FEN on each move and never implements its own chess rules.

It refuses all unsupported annotations, NAGs, comments, alternate lines, multiple games, castling notation, promotions and any move that the canonical Board cannot legally play. The structured result is explicitly NOT a typeset Braille game score, not paginated, not a variation-tree certificate, and not professional proof of UKAAF 4.x paragraph layout.

Tests use short legal algebraic games, illegal move sequences, contradictory/multiple PGN input and otherwise legal but not-yet-qualified special moves. Full chess-game conversion and 2015 text-layout approval remain open.

## Still required

Complete UKAAF 2015 3.x move notation, variations and textual analysis; UKAAF 4.x/5.2/6 layout and tactile diagrams; OCR/provenance; official proofreader and British chess-Braille expert approval; actual library/reader context; real embosser/BRF/eBraille; legal sample corpus; broad roundtrip and negative corpus; full Section 55 release and institutional quality gates.

At present this is **a standard-grounded partial component, not a finished Chapter 55 nor an alternate Braille standard**.
