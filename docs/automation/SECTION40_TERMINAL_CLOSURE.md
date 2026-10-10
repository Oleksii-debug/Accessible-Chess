# Section 40 — terminal closure

**Status:** DONE — TERMINAL under Simplified Section Closure Protocol v3.

**Scope:** Section 40 only. Existing Sections 0–39 and 41–45 remain preserved. Protected 40.2 and 40.5 were reused without reimplementation.

## Canonical integration

- Source-preserving lineage: protected PR #2494 → scoped PR #2518 → canonical finisher PR #2545.
- Qualified code candidate: `58d82eaea2221206d534116e3563d0053b04ae75`.
- Main-preserving convergence parent: `a985d94c3eb71073fe31df71634316f232b7327c`.
- Integrated main merge: `bfe94904c3b4bb8ab66108455483b1a934612d5d`.
- Convergence parent to merge: one topology commit, zero file delta.
- No alternate parser, GameTree, chess authority, Library authority, or speculative format support was introduced.

## Executed exact-SHA qualification

### Revised Section 40 Offline Library QA

Run `38046483879`, exact code candidate `58d82ea…`:

- Ubuntu 24.04 job `114196950975`: SUCCESS; 19 workflow steps; 120 tests.
- Windows 2025 job `114196950981`: SUCCESS; 19 workflow steps; 120 tests.
- Exercised source/provenance, DOCX cancellation and BookDocument semantics, private seed identity/race safety, real corpus, rights, negative cases, restart/reimport, TEST_BUILD, PUBLIC_RELEASE, owner runtime seed, three-archive readback, and package artifacts.
- Ubuntu artifact digest: `sha256:14765f1789061c64f87eba0605477a227dbcd7c2f7914f4c07a39086a680e6a1`.
- Windows artifact digest: `sha256:0230798fed8e9edaecb48f3db223ea20d1f2471e2f13e8b9f1a27d0186393219`.

### Canonical real offline Books

Run `38046483834`, exact code candidate `58d82ea…`:

- Ubuntu 24.04 job `114196950383`: 45/45 PASS.
- Windows 2025 job `114196950512`: 45/45 PASS.
- Exact original bilingual workbook, historical Réti study, Books/Training/Board integration, restart and original starter content remained valid.

Total Section-40 qualification: **165 tests per OS / 330 test executions**.

## Acceptance mapping

- **40.1 DONE:** TEST_COLLECTION contains real Stockfish PGN, four original annotated games, one historical Réti study, 16 advanced and four extreme CC0 tasks, course/training data, and ten importable Ukrainian/English 12-lesson EPUB3/HTML/DOCX/TXT/Markdown books; small/medium/large corpus bands remain catalogued.
- **40.2 DONE — protected/reused:** title, author/owner, language, format, source URL, size, checksum, rights, import state and reload metadata remain distinct from public external-link records.
- **40.3 DONE:** workers/builders prepare the corpus and owner seed automatically; ordinary own-book/PGN/qualified ChessBase imports continue through existing canonical program routes.
- **40.4 DONE:** prepared Library, Books, Training, Board and Search content opens without manual corpus assembly or network access; existing private seed data is preserved and only disposable QA copies are extended.
- **40.5 DONE — protected/reused:** TEST_COLLECTION and PUBLIC_RELEASE are separate; uncleared third-party bytes are excluded from public release; controlled cleanup is explicit.
- **40.6 DONE:** TEST_BUILD and PUBLIC_RELEASE were actually built and read back on Ubuntu and Windows; checksums, source identity, negative/tamper, restart/reimport and cleanup boundaries passed.

## Proven repairs before acceptance

1. Restored the protected original advanced-training generator rather than inventing a replacement.
2. Repaired the obsolete 25-item Books assertion while retaining the exact original 24-booklet invariant.
3. Repaired detached Training revision rollback.
4. Included the already accepted Section45 local studio and all 12 accepted Section42 RhosGFX originals plus provenance/license in the Windows package fixture.
5. Marked the SHA-pinned Section42 source set `-text`, preventing Windows CRLF conversion without weakening checksum enforcement.

## Honest boundary

CBF+CBI, 2CBH, CBONE and other unavailable or uncleared third-party material are not represented as supported or publicly redistributable. Physical Windows/NVDA owner acceptance belongs to the final whole-product release gate under v3 and is not falsely claimed here.

Machine record: `docs/corpus/SECTION40_TERMINAL_RECEIPT.json`.

**TERMINAL LOCK:** ordinary workers must skip Section 40 unless a concrete regression, invalid evidence, changed acceptance contract, or later integration break is recorded first.
