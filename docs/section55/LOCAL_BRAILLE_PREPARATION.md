# Section 55 — Local chess-book PEF/BRF preparation (UNVERIFIED)

**Status:** PARTIAL IMPLEMENTATION. Not a qualified Braille service. Not print-ready. No physical printer test, literary Braille reader acceptance or dedicated chess Braille code qualification. This module must never be used as a substitute for a verified embosser workflow.

## Supported local inputs

- One authorized BookDocument JSON (--book-json) or one TXT/Markdown book (--source-file) through the existing canonical acs.book_text_import. For Markdown, chess games and FEN positions are recognized only where explicitly marked with the canonical fenced syntax. No AI text recognition or silent position guessing.
- A separately installed Python Liblouis package, a readable local translation table file (--table-file) with exactly the same filesystem identity as --table-id, and a caller-supplied version label. A single-file SHA-256 pin does not attest included tables or prove language/edition/chess notation correctness.
- Explicit source rights assertion (--rights-confirmed, --rights-basis) and an appropriate local output folder. All material remains on the computer.
- Six-dot PEF, single-volume/simplex; optional derived BRF with explicit en-us-brf.dis six-dot Braille ASCII display map. No custom Braille invented and no eight-dot printing.

## Example for a lawful locally owned Markdown chess book

This is a command template, **not** a claim that any arbitrary installed table or printer is qualified. From repository root:

    python tools/section55_braille_pef.py --source-file /private/books/authorized-book.md --table-file /private/liblouis/en-ueb-g1.ctb --table-id /private/liblouis/en-ueb-g1.ctb --table-version locally-reviewed --language en --device-model UNQUALIFIED-PREVIEW --cells-per-line 32 --lines-per-page 25 --rights-confirmed --rights-basis "I hold required reproduction rights" --emit-brf --display-table en-us-brf.dis --output-folder /private/output/new-book-package

**If the table includes dependencies, the local main-table hash alone is not complete evidence of the translated code. This is an open gate.** The tool may reject a document rather than guess line breaks, interpret malformed FEN/PGN, or silently normalize ambiguity.

Files in the newly reserved package directory:

- chess-book-unverified.pef — UTF-8 Portable Embosser Format (PEF) with mandatory format/identifier Dublin Core metadata.
- chess-book-unverified.brf — optional Braille ASCII version of the same PEF pagination and row content; still unverified.
- quality-report.json — original source SHA-256, PEF and optional BRF SHA-256, table SHA-256 and identity, page metrics, warnings, rights declaration, and explicit negative print-ready status.

The --book-json book.json argument may replace --source-file; it is mutually exclusive. If BRF is not requested, omit both --emit-brf and --display-table.

## Independent local package consistency recheck

    python tools/section55_verify_bundle.py --folder /private/output/new-book-package --original-source /private/books/authorized-book.md --table-file /private/liblouis/en-ueb-g1.ctb

A PASS means **only** that the supplied source bytes, declared hashes, PEF structure, BRF map and exact reproduced provisional BRF correspond. A PASS **never means** that the Braille translation, chess score, rights, pagination for a particular embosser, tactile legibility, or output is qualified.

This standalone verifier does not need an installed Liblouis because it checks emitted cells, not lexical or chess-code correctness. When --table-file is supplied, it independently checks the complete local relative-include file inventory and pinned digest; without this flag table bytes are explicitly NOT rechecked. Local table identity is not independent chess-Braille rule certification. The original file must remain available. If any input is modified or a manifest is falsely upgraded to print_ready: true, the verifier fails.

## Accessibility and privacy

- CLI communicates success/failure via plain console text and process exit code (0 only for a successfully prepared or locally consistent **unverified** package, 2 for refusal).
- File names are deterministic and can be navigated using Windows 11 and NVDA.
- No remote AI, OCR, provider, printing or network operations occur.
- A new output folder is mandatory. Existing folders (including empty ones) are preserved, not replaced.
- On failure before publication, unpublished temporary files are cleaned up. Raw private paths/text are not printed in error messages.
- The package contains the explicit rights_basis that the user typed. Use a privacy-appropriate generic rights basis if it would otherwise reveal private legal information.

## Optional source-readable HTML preview for NVDA

To create the unverified, keyboard-navigable local HTML preview together with a PEF package, append --emit-html to the preparation command. Its file name is chess-book-unverified.html. You can open it directly in a browser without network access. Use NVDA heading navigation (H), link navigation (K), and the page links in the navigation section. The original semantic chess text, including supported FEN and diagram alt text, is exposed separately; the Unicode Braille cell pages are visually shown as UNVERIFIED and are not presented to NVDA as a trustworthy transcription.

The preview uses only escaped original source text, static semantic HTML, restrictive CSP, a skip link, and a heading-based table of contents. It contains no JavaScript, tracking, or external resources.

The quality report includes an HTML SHA-256 and explicit html_print_ready=false. The independent verifier reconstructs the original source semantics and the HTML output from the original book and PEF before accepting a package. This output does NOT implement the finalized eBraille specification, literary chess-Braille editorial acceptance, or physical embossing.

## Remaining mandatory Section 55 gates

Actual supported languages/Liblouis full table-closure pinning; formal standardized chess notation and independent forward/back-translation; rights-evidenced multi-edition intake/PDF and OCR/PGN/FEN; tactile diagram and real embosser profiles (duplex, page size, paper geometry); actual eBraille, pagination and large-volume book queue/restart; professional qualified chess Braille QA; lawfully sourced corpus; validated hardware print proof and blind-reader acceptance; accessible end-user UI and packaging; product-level integration. No Section 55.x subsection is DONE.

For exact branch/state see docs/section55/IMPLEMENTATION_STATUS.md and the canonical PR #2529.
