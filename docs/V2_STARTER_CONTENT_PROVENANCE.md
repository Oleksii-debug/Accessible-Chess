# V2 offline starter Books/Training provenance

Status: W3 / P0-F source evidence. This document does **not** set `HUMAN_ACCEPTED=YES` or `NVDA_VERIFIED=YES`.

## Scope

The built-in V2 starter corpus lives in `acs/starter_books_training_content.py`. The authored corpus uses the canonical `BookDocument` model and contains Ukrainian prose plus short self-check questions. `acs/starter_books_training_runtime.py` converts those self-check blocks into the canonical one-move Training contract while preserving each authored question and factual answer in the readable Book flow. The final product then consumes the result through the existing `BookReader`, Books WebView/native menu path, `book_training` bridge, canonical chess core and Training workspace. No second content engine, remote service, browser download, LLM, or network request is used at runtime.

The corpus contains 27 Ukrainian tutorial materials and 135 Training exercises. Every packaged Training exercise is required to pass `build_book_training_material`, so its expected answer is a legal canonical chess move rather than arbitrary quiz text. The packaged final-product composition opens the aggregate starter course automatically as the initial Books document, while the existing Training route moves to the first canonical exercise when needed.

## Provenance and rights inventory

All prose, questions and answers in this starter corpus were newly authored for the Accessible Chess project on 2026-09-11. They do not copy third-party books, articles, annotated games, puzzle databases, or proprietary chess-course text. They contain only original explanatory prose plus ordinary chess facts and terminology.

The semantic metadata records the rights statement:

`Project-authored for Accessible Chess; no third-party text or games`

There are no bundled third-party media files, web resources, external URLs, credentials, tokens, cookies, user data, browser profiles, or private logs in this W3 corpus.

## Deterministic inventory

`starter_content_manifest()` is the machine-readable inventory. The W3 acceptance gate requires:

- at least 24 distinct tutorial materials; current corpus: 27;
- at least 100 canonical Training exercises; current corpus: 135;
- all 135 packaged exercises accepted by the canonical `BookDocument -> book_training -> chesscore.Board` path;
- Ukrainian language metadata;
- a non-empty provenance/rights statement;
- unique semantic block identifiers;
- valid canonical exercise FEN values;
- no network URL dependency in the aggregate course;
- deterministic first-run Books and Training availability through the existing V2 application.

## Acceptance boundary

Automated tests can prove schema validity, inventory counts, semantic parsing, legal Training conversion, first-run application composition and Training startup. They cannot prove physical NVDA behavior. Oleksii must perform the final packaged Windows/NVDA acceptance before `NVDA_VERIFIED` or `HUMAN_ACCEPTED` may be changed to true.
