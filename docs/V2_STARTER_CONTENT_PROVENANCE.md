# V2 offline starter Books/Training provenance

Status: W3 / P0-F source and redistribution evidence. This document does **not** set `HUMAN_ACCEPTED=YES` or `NVDA_VERIFIED=YES`.

## Canonical product path

The original project-authored Ukrainian seed lessons remain in `acs/starter_books_training_content.py`. The P0-F quality layer is `acs/starter_books_training_quality.py`. It reuses those authored explanations as source material, expands them into self-contained learning materials, and builds position-specific exercises exclusively through the canonical `BookDocument`, `Exercise`, `Diagram`, `VariationTree` and `chesscore.Board` contracts. `acs/starter_books_training_runtime.py` publishes that quality course through the existing Books/Training route; it does not invent moves or create a second quiz, chess, Books or Training engine.

The aggregate built-in course remains immediately available offline on first run. It contains 27 distinct substantial Ukrainian learning materials and 135 position-specific canonical Training exercises. Every material contains extended explanatory prose, a semantic diagram, a FEN-rooted variation and five exercises. The course deliberately retains the existing product count of 27 materials / 135 exercises while replacing the former arbitrary opening-move adapter with exercises whose prompt, FEN and legal answer belong to the same position.

## Project-authored provenance and redistribution license

All W3 starter prose, self-checks, diagrams/position descriptions and Training prompts are project-authored for Accessible Chess. They do not reproduce third-party books, commercial databases, annotated games, puzzle collections, articles or proprietary course text.

The project-authored W3 starter corpus is distributed as:

- license identifier: `CC-BY-4.0`;
- license name: Creative Commons Attribution 4.0 International;
- attribution: `Accessible Chess project`;
- embedded redistribution terms: copying, redistribution and adaptation are permitted with attribution to the Accessible Chess project; no warranty is provided;
- source type: `project-authored`;
- source identity: per-material `urn:accessible-chess:starter:...` URI.

`starter_quality_manifest()` is the machine-readable source/provenance/license inventory. Each material entry carries its own source URI, source type, license identifier, license terms, attribution, word count, exercise count, position FEN inventory, Diagram flag and VariationTree flag. This is the W3 P0-F redistribution manifest; the older `STARTER_CONTENT_RIGHTS` string remains historical source metadata and is not used as a substitute for the explicit license record.

No third-party media, credentials, tokens, cookies, private logs, browser profiles or network-fetched runtime assets are introduced by this W3 fix-forward.

## Semantic acceptance

The strengthened W3 gate requires all of the following on Ubuntu and Windows where applicable:

- at least 24 distinct substantial project-authored learning materials; current course: 27;
- at least 500 words of instructional prose in every material, in addition to semantic lists/diagrams/variations/exercises;
- exactly five position-specific Training exercises per material; current course: 135 total;
- at least 24 distinct FEN positions in the aggregate course;
- a semantic `Diagram` and `VariationTree` in every material;
- every Training answer accepted by `chesscore.Board.parse_move` from that exercise's own FEN;
- every exercise accepted by the canonical `BookDocument -> book_training` material builder;
- unique semantic block IDs and clean `BookDocument.validate_structure()` output;
- deterministic offline first-run Books/Training composition with no network dependency.

The position set includes multiple common opening structures plus isolated rook, bishop, knight and queen movement, a pawn endgame, castling rights and promotion. Opening-derived FEN values are produced by applying legal coordinate moves through the canonical Board; custom positions are likewise validated by Board before publication.

## Release boundary

This W3 repair closes only the Books/Training semantic-content and redistribution-license portion of P0-F. W2 owns the lawful PGN/sample ACSDB/Library corpus, W4 owns accessibility/hotkey feedback, and W5 owns serial integration and final package-content proof. The final Windows ZIP must still prove that the exact integrated content is physically present after fresh extraction, discoverable and usable offline. Physical NVDA acceptance remains Oleksii-only; therefore `HUMAN_ACCEPTED=NO` and `NVDA_VERIFIED=NO` remain mandatory until that test occurs.
