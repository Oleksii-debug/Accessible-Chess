# Section 54.1 — PDF text evidence probe (PARTIAL, NOT DONE)

Owner-authorized, independent additive lane stacked on Section54 parent PR #2530,
starting at parent head `b40bc6528742bf24340185fc97a86d6ef8e07bc4`.
It does not alter any parent-worker source, existing BookDocument, parser,
Board, Stockfish, Sections 0–53 or Section 55.

## Source and behavior

- `acs/format_factory_pdf_probe.py` calls the EXISTING
  `inspect_factory_source` identity/capability entrypoint.
- The optional, pinned-on-CI `pypdf==5.9.0` parser runs in a spawned
  child process; no filesystem, network, model or external API operation.
- The input/source is at most 8 MiB, pages at most 128, page text at
  most 20,000 characters each, total text at most 300,000 characters;
  caller-set wall-clock timeout is limited to 0.1–60 seconds.
- Original PDF SHA-256, file-page-index anchors, explicit empty-page warnings,
  and source-derived page text are retained.
- Every extracted page remains `REVIEW_REQUIRED`. Printed-page correspondence,
  reading order, diagrams, SAN/FEN, OCR, author identity, rights and release
  approval are always explicitly NOT PROVEN; the module does NOT create a
  second BookDocument or claim a full PDF book importer.
- Encrypted PDFs, spoofed extensions, malformed files, blank pages,
  excessive pages, invalid limits, and parser errors are negative-tested.
- POSIX child has a 512 MiB address-space limit; Windows child does NOT yet
  have a Job Object memory quota. An in-flight malicious compressed stream
  can require substantial memory; this remains a Windows/release security
  acceptance gate. Do not wire this preview probe to arbitrary user files
  as a production-trusted PDF feature before memory and parser sandbox review.

## Additive canonical text-only projection

- `acs/format_factory_pdf_projection.py` reuses the existing `import_text_book(..., source_format='txt')` to create the ONE canonical `BookDocument` from ALL extracted pages without inventing headings, games, FEN, or diagrams.
- Blank/unreadable pages block the entire projection, rather than omitting pages. A page-to-projected-line map and separate original-PDF SHA256 and projected-text SHA256 are retained.
- Output is a private `REVIEW_REQUIRED` preview only, with provenance/reading-order/chess/rights warnings. This is not full PDF ingress or a publishing path.
- `tests/test_section54_factory_pdf_projection.py` adds six executable canonical-integration/negative scenarios (including duplicated-importer-warning regression); their real-repository Windows/Ubuntu outcomes are **NOT YET CONFIRMED** while exact-head CI is pending.

## Evidence and open gates

Sixteen isolated local tests were run successfully on Python 3.11-compatible syntax
using the installed `pypdf 5.9.0` library, including an actual generated
PDF text-page extraction, encrypted-PDF rejection, page-count rejection,
source spoof rejection, fabricated approval rejection and private error redaction. **Local tests used temporary minimal canonical-intake and BookDocument importer stubs**, not the real checkout (GitHub DNS
is unavailable in the working container); therefore these are focused unit
smokes only, NOT real repository integration or acceptance. The committed
test imports the real parent-branch canonical factory intake and should be
verified by the added Ubuntu 22.04 / Windows 2025 GitHub Actions workflow.

No live NVDA, production Windows/Web UI, EPUBCheck, OCR/scanned-PDF conversion,
verified chess semantics, rights adjudication, source book end-to-end rendering,
signed output, hard Windows memory ceiling, or human acceptance was performed.
No Section54 subsection or parent is marked DONE. Parent #2530 owns eventual
integration; do not merge this stacked lane directly to main.
