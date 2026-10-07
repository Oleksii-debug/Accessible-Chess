# Section 5 — Book formats and semantic BookDocument — terminal closure audit

Canonical plan authority: **SECTION 5 — Книжкові формати і semantic BookDocument**.
Accepted predecessor: Section-4 merge `ade920d6efadb51383a0f422a0a8a15ba5c29000`.
Hard dependencies Sections 0–3 are terminally DONE; Section 4 is also terminally integrated on this ancestry.

## 5.1 Semantic BookDocument

The Product uses one canonical `BookDocument` model with bounded, validated semantic blocks:
Heading, Paragraph, ListBlock, Position, Diagram, Game, VariationTree, Exercise and Note, with durable identifiers/source anchors.
Current `acs/bookdocument.py` blob: `23249894e2e7d9c3b2c0602515188000ea846a41`.

## 5.2 Approved adapters and capability boundary

Approved repository-controlled semantic adapters on this accepted Product are:
- TXT / Markdown: `acs/book_text_import.py` (`18f26a228022f682c0d0948423282dfe29ab4b54`);
- HTML / XHTML: `acs/book_html_import.py` (`8400a3a90a17e99406b99c60a7af1baefa1f784d`);
- EPUB: `acs/book_epub_import.py` (`c6c3144f2582d9e0489ece8ed9c602af40d0956d`).

DOCX/PDF are not silently claimed by this Section: no canonical direct DOCX/PDF semantic adapter is promoted here. A future conversion path would require an explicit capability contract rather than filename recognition.

## 5.3 Chess blocks and exact reading return

Explicitly marked chess content routes through existing canonical FEN/PGN/GameTree/Board authorities. `book_game_content.py`,
Book Board workflows and BookReader navigation retain the Book reading origin and return point rather than creating a second chess parser/rules engine.

## 5.4 Bounds, cancellation, malformed input and durable reading identity

TXT/Markdown, HTML/XHTML and EPUB adapters enforce source/visible-text/block/resource budgets and stable typed failures.
EPUB validates ZIP/OCF/XML/path topology and rejects unsafe/malformed/resource-hostile containers. Active import supports bounded cancellation.
BookReader + Book progress preserve durable block/anchor identity and reject stale or malformed snapshots fail closed.

## 5.5 Lawful real/stress book evidence

The exact BookDocument/BookReader/runtime blobs on this candidate are byte-identical to the terminal Section-6 accepted Product
`910496bf8dd9c1cb4429c2c0bd9080ea4223b7e3`, which already binds substantial lawful offline Books/Training content,
large reading journeys, starter provenance and clean-install content application. Section-5 format regressions additionally cover
Markdown, HTML/XHTML, EPUB, Unicode/legacy text, semantic lists, chess blocks, malformed containers, resource bounds and cancellation.

No external proprietary book corpus is fabricated. Evidence that is not lawfully redistributable is not treated as a hidden requirement.

## Exact closure delta

This finisher is evidence-only relative to `ade920d6efadb51383a0f422a0a8a15ba5c29000`:
- `.github/workflows/section5-book-formats-closure.yml`
- `docs/automation/SECTION5_CLOSURE_AUDIT.md`

No Book runtime, chess semantics, Library, UI or persistence implementation changes are made.

`SECTION5_PRODUCT_MUTATION=NONE`
`HUMAN_TESTED=NO`
`NVDA_VERIFIED=NO`
