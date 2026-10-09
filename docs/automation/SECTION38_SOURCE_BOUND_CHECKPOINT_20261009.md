# Section 38 source-bound Book/Library ingress checkpoint

Date: 2026-10-09

Status: **PARTIAL — NOT TERMINAL DONE**

Canonical authority: [Accessible Chess Product Sections 0–53](https://docs.google.com/document/d/1ITsUBFwwETRICctcOWLd6atuMcCFZg6v5-wVFumIyxE/edit), Section 38. This is **not** old Product Section 38 (Windows release infrastructure) and cannot close its historical issue #2463.

## Implemented on this focused candidate

- Reused existing canonical `Version2Application.prepare_book_open`, `import_epub_book`, `open_book_library_source`, `LibraryImportService`, `AcsDatabase` and chess PGN parser; no duplicate chess or book authority.
- Corrected a real native-product reachability defect: `.epub3` had previously been accepted by Book-to-Library import but rejected by the actual user Book Open preparation. Both native English/Ukrainian book picker and Library import picker now offer `.epub3`.
- Section 38 independent test-only PGN inputs (Cotswold 113 games, Alekhine 1661 games) now require *both* the existing observed original SHA-256 and exact expected canonical game count, with bounded size, symlink rejection, parser-warning and mutation guards.
- Existing original Project Gutenberg Book receipts (TXT/HTML/EPUB3) are bound to their observed original byte digests; a changed live publisher download fails instead of silently becoming a new PASS.
- In addition to Library games projection, original books must pass actual native Book Open semantic preparation, with nonempty BookDocument blocks. Missing assets, flattened tables and unreadable spine pages yield `PARTIAL_SEMANTIC_LOSS` rather than an unqualified full-fidelity PASS.
- Actual PGN to ACSDB import, repeated import idempotence, backup/restart, cancellation rollback remain in the existing Section 38 gate.
- New negative/source-identity tests and an explicit two-OS CI job test the native EPUB3 seam. Exact-source reports are retained as CI artifacts.

## Real-source evidence reused, not re-fabricated

- Protected Section 37 terminal receipt: 14 locally qualified files, 1,596 EPD/FEN rows, 12,092 Stockfish PGN games, four real annotated games, 113/113 independent original CBV→CBH→ACSDB readback; CBF+CBI/2CBH/CBONE unavailable.
- Protected Section 39 terminal receipt: 59/59 Section-39 local tests, 99/99 adjacent tests, three original CBH families with 33/33 companions; 16-format READ/WRITE/ROUNDTRIP classification, including actual unsupported/blocked cells.
- Historical `docs/corpus/SECTION38_REAL_CORPUS_INTEGRATION.json` is a prior observed source report, **not** an execution receipt for this candidate SHA. Its prior Book `PASS` with missing images/table loss must not override new stricter semantics.

## Unclosed Section-38 obligations

1. Obtain or independently verify additional legally available ORIGINAL multi-format third-party books, DOCX and PDF where importer/policy supports; do not equate generated/derived DOCX/EPUB with an external publisher original.
2. Expand actual large/compressed PGN (including Chess960, nested RAV/NAG, live-broadcast licenses), FEN/EPD/ECO and advanced bilingual corpus coverage through current canonical services, with measured user-facing Library/Training/Search/Board/Web/Windows readback.
3. Qualify real CBH/CBV with full companions and independent readback on the *exact new Section-38 integration candidate*. Full CBF+CBI, 2CBH and CBONE originals remain unavailable; preserve honest `BLOCKED/UNSUPPORTED` rather than claiming support.
4. Receive executed exact-head Linux and Windows CI outcomes and integration-to-main readback, including negative/restart and keyboard/Book navigation boundaries.
5. Merge one nonduplicating Section-38 candidate into current main, then update `SEQUENTIAL_CLOSURE_STATE.md` and the official plan only if 38.1–38.6 meet acceptance.

Rights: external original files here are **TEST_ONLY**, excluded from PUBLIC_RELEASE unless redistribution rights are independently cleared. No proprietary formats or commercial books are fabricated or copied into repository ZIPs.

**No DONE, 100%, Windows/NVDA pass, or CI-green claim is made by this checkpoint.**


## Additional preserved and integrated source work (candidate follow-on)

- Five exact Git blob identities from protected PR #2494 were reused without rebuilding: `tools/revised_section38_stockfish_owner_seed.py`, `tests/test_revised_section38_owner_seed.py`, `tests/test_revised_section38_official_openings_library.py`, `tests/test_revised_section38_stockfish_real_library.py`, and `tests/test_revised_section38_real_cbh_oracles.py`. All now live on this candidate; no protected source binary was copied beyond what was already in accepted main.
- The genuine original Stockfish ZIP / Lichess ECO TSV test suites and their real ACSDB import, idempotence, cancellation and restart tests are wired to the source-bound Linux workflow. Tests and pre-existing corpus are preserved, but queued jobs remain **UNEXECUTED**, not PASS.
- The previously implemented, bounded DOCX canonical BookDocument converter `acs/book_docx_import.py` and its seven documented integration/security/restart tests were transferred byte-for-byte from PR #2494. The native product owner `Version2Application.prepare_book_open` now allows `.docx` files and routes them to that parser after bounded source snapshot reading. Both UA and EN Book picker filters display Word files; the games-only Library importer is deliberately unchanged because this DOCX adapter publishes readable prose, not guessed games.
- This DOCX implementation is an **implemented internal read-only capability**, with only derived project-controlled interoperability fixture and genuine original Gutenberg TXT→derived DOCX source chain covered by that preserved test. An independently downloaded third-party original DOCX is still missing; the original-format corpus qualification may not be declared PASS on the strength of generated files.
- PDF native semantic import remains explicitly unsupported; unavailable full CBF+CBI/2CBH/CBONE remain blocked. Physical NVDA remains the terminal whole-product gate.

The complementary [PR #2516](https://github.com/Oleksii-debug/Accessible-Chess/pull/2516) owns the independent external CBV/CBH backend and publisher-matched PGN oracle; do not duplicate it in this lineage. This checkpoint continues to assert **Section 38 OPEN / NO TERMINAL DONE** pending executed exact-head tests, dependency-safe integration, accepted user-facing corpus evidence and canonical registry closure.
