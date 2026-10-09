# Section 54 — bounded source intake implementation checkpoint (2026-10-09)

## Exact scope

This checkpoint targets the foundational intake slice of **54.1** only. The parent **Section 54 is PARTIAL / NOT DONE**. No 54 subsection is declared terminal at this checkpoint. Section 51 is not touched.

New additive source: `acs/format_factory_intake.py`; regression tests: `tests/test_section54_source_intake.py`; dedicated Ubuntu/Windows workflow: `.github/workflows/section54-source-intake.yml`.

Implemented capability: immutable in-memory source-byte SHA-256 and bounded identity, extension-content mismatch denial, conservative MIME/signature detection of PDF, JPEG, PNG, ZIP/EPUB/DOCX, PGN and structured text. ZIP metadata rejects traversal, duplicate names, special-file entries, encrypted entries, individual/aggregate size overruns and extreme expansion. EPUB container identification does not claim successful EPUB content parsing. Supported TXT/Markdown, HTML, EPUB are delegated to existing BookDocument importers; no alternative chess parser, FEN authority, text converter, or privileged filesystem/network activity is introduced.

**Truthful status matrix**

| Source | Identification | Qualified semantic import |
|---|---|---|
| TXT/Markdown | byte-detected, bounded | reuse existing importer; output only after canonical import SHA check |
| HTML/XHTML | byte-detected for common HTML signatures | reuse existing HTML importer; other XHTML declarations may be unsupported |
| EPUB | ZIP structure/mimetype sniffed | qualified only if existing canonical EPUB importer accepts full package |
| PGN | chess headers detected | PARTIAL: native PGN authority exists elsewhere; no BookDocument fabrication |
| DOCX | OOXML archive identity recognized | PARTIAL: future approved semantic importer |
| PDF/image | signatures recognized | PARTIAL: no invented OCR/diagram/ChessCore output |
| generic ZIP, proprietary ChessBase, unknown | identity or unsupported classification | UNSUPPORTED; explicit error |

## Acceptance still open

- 54.1: breadth of file formats, approved PDF/OCR/DOCX/ChessBase import, edition/author/year/page/anchor provenance, single-source canonical book journey.
- 54.2–54.4: full semantic provenance, multimodal/OCR provider routing and canonical diagram/GameTree legality.
- 54.5–54.7: user-consented source lookup, natural-language policy/UI and NVDA form.
- 54.8: tagged PDF/EPUB3/DOCX/PGN conversion, loss manifest and output readback.
- 54.9–54.12: per-book durable queues, token envelopes, idempotent checkpoints and failure recovery.
- 54.13–54.15: privacy, QA of real lawful books, Windows/Web product integration, acceptance, final shipping provenance.

## Verification and integration rule

The committed test file covers deterministic source identification, digest, canonical import reuse, archive traversal and duplicates, forged extensions, malformed EPUB/ZIP, unsupported formats and privacy-preserving path display. **Presence of tests is not evidence of their execution.** Do not call tests PASS before a completed exact-head CI or actual local execution. No authenticated external source was transmitted; no paid API was called. Preserve Sections 0–53 accepted work and 55 separately. After qualification, converge only through the canonical main release path. No DONE without whole 54 acceptance.
