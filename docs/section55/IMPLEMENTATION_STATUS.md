# Section 55 — Chess Braille production handoff

Status: **PARTIAL / IMPLEMENTATION OPEN / NOT DONE**.
Canonical owner scope: Drive ACCESSIBLE CHESS SECTION PLAN, 55.1–55.16.
Do not replace that scope, accepted Sections 0–53 or the canonical Board/PGN/Book authorities.

## Canonical partial implementation
- PR #2529, branch feature/section55-chess-braille-pef-foundation-20261009.
- Branch creation base main e610db418ff28025711540c43c3552f873791fad.
- Module: acs/chess_braille_factory.py; optional Liblouis formal-translator seam with table SHA and version pin, six-dot bounded PEF preparation, source-rights gate, canonical BookDocument/Board/PGN reuse, checksum and UNVERIFIED_REQUIRES_DECISION report.
- Local-only CLI: tools/section55_braille_pef.py, explicit rights flag, no paid APIs, no implicit publishing or destructive overwrite.
- Synthetic negative and structural tests: tests/test_section55_chess_braille_factory.py.
- Two-OS CI workflow: .github/workflows/section55-braille-pef.yml; check exact live job conclusion. QUEUED is NOT PASS.
- No main merge or release integration is claimed. Physical embosser, Braille reader and specialist qualification remain unproven.

## 16 subsection acceptance statuses
- 55.1 PARTIAL: profile/formal transliterator boundary; real tables/grade/language/chess notation rules and included table dependency closure missing.
- 55.2 OPEN: original one-book intake/OCR/edition matching, source-repair and legal corroboration; only preexisting canonical JSON intake wired.
- 55.3 PARTIAL: reuse canonical FEN/PGN, but full legal chess semantics and diagram verification missing.
- 55.4 OPEN: formally certified Braille chess abbreviation/variation/exercise notation.
- 55.5 OPEN: tactile graphics models and reference qualification.
- 55.6 PARTIAL: unverified six-dot PEF only; BRF/eBRL and qualified digital reading remain missing.
- 55.7 PARTIAL: row/column bounds only; real embosser drivers/paper/duplex/volume layout and sample proof missing.
- 55.8 OPEN: autonomous one-book OCR, correction, formal Braille, revalidation and output pipeline.
- 55.9 PARTIAL: structure and checksums only; independent round-trip/translation and print-ready QA missing.
- 55.10 OPEN: braille/NVDA display, BookReader/GameTree anchor synchronization.
- 55.11 PARTIAL: preliminary PEF and quality JSON; no complete qualified institution bundle/UI.
- 55.12 PARTIAL: explicit rights assertion/local-only operation; legal, privacy, retention and authorization qualification outstanding.
- 55.13 OPEN: user token limits, book queue, pause/resume, 429 and restart recovery.
- 55.14 OPEN: independent legal real-book corpus, multi-language/print-device/performance/reader qualification.
- 55.15 OPEN: industrial evidence and permitted research decisions.
- 55.16 OPEN: full accessible Windows/Web end-to-end integration and qualified print-ready/live-main closure.

Terminal gate progress: **0 of 16 DONE (0%)**. Source work is a provisional foundation only.
All results are UNVERIFIED_REQUIRES_DECISION; no print-ready certification is allowed.

## Resume in one canonical lineage
1. Re-read current main and exact PR #2529 head, CI, comments, and possible parallel Section-55 work before modifying.
2. Repair only proven failures in this PR. Do not duplicate an implementation or invent green evidence.
3. Qualify real licensed Liblouis dependency closure, chess notation/diagram references and a lawfully usable book.
4. Qualify real embosser and Braille reading configurations, independent correction and negative/recovery/performance/legal/privacy tests.
5. Integrate user-facing Windows/Web and institution bundle into canonical main, verify exact-main source and acceptance.
6. ONLY after every 55.1–55.16 requirement and evidence is satisfied, record terminal DONE in GitHub state, Drive plan and live registry. Preserve current NOT DONE until then.

## Continuation checkpoint — 2026-10-09, after initial PR

- Added acs/chess_braille_brf.py: provisional NABCC six-dot Braille ASCII BRF from source-hash-pinned PEF with strict page/row/metadata/layout validation; explicit no-print-readiness result.
- PEF creator now emits mandatory PEF 1.0 Dublin Core dc:format and dc:identifier, checks XML legality, includes canonical FEN/side-to-move/piece-square inventory, and uses Liblouis dotsIO | ucBrl together as required for Unicode Braille.
- CLI now supports either one canonical BookDocument JSON or one local .txt/.md via the existing acs.book_text_import parser. Unproven images/content, unsupported formats, source change during work, table mismatch or table drift fail closed. Optional --emit-brf and explicitly selected en-us-brf.dis create an unverified BRF companion. Both original source bytes and output files receive SHA-256 fingerprints.
- No-clobber output folder creation uses exclusive mkdir; pre-existing files/directories are preserved. Quality report is emitted last. No remote providers, paid work or automatic printing.
- Added tests/test_section55_chess_braille_brf.py and tests/test_section55_local_cli_package.py, including source/content/metadata mutation negatives, Liblouis synthetic mode flags, Markdown intake and output preservation.
- Sections 55.2 and 55.6 therefore have PARTIAL source-format/format-output progress, not closure. Neither a synthetic Liblouis module nor an arbitrary table filename is a certified translation.
- Exact GitHub Actions results must be read from latest PR head. The latest observed runs were QUEUED, NOT GREEN. No test execution, real device, legal real-book sample, specialist acceptance or main integration is claimed.
- Keep this PR as canonical single Section 55 finisher, watch live main changes, and never promote any subsection without its full own acceptance evidence.

## Second continuation checkpoint — source/PEF/BRF bundle verification

- New acs/chess_braille_bundle.py and tools/section55_verify_bundle.py independently re-open provisional PEF/BRF, exact original input bytes and JSON quality report; reject missing/extra files, corrupt SHA-256, false print/device qualification, loss of warnings, wrong display map and source mismatch. A passing consistency verification remains **UNVERIFIED**, never a specialist or physical acceptance.
- The generation CLI now runs that same independent consistency gate on a still-private unpublished directory before promoting artifacts. It refuses to overwrite existing output and rolls back its own temporary files on verification failure.
- New tests/test_section55_braille_bundle.py checks PEF-only and PEF+BRF positive synthetic bundles; bad source/PEF/BRF/manifest, unexpected/missing files, false DONE-like status and CLI privacy negative outcomes.
- The complete 64-character BRF display map is checked against an explicit independent expected dot-notation fixture from the published Liblouis en-us-brf.dis table.
- Native translation is now bounded to <=8192 source characters per semantic segment; XML-invalid controls fail before Liblouis. Multi-line chess descriptions/PGN and blank lines are handled as physical PEF lines rather than passing raw newline controls to the translator.
- docs/section55/LOCAL_BRAILLE_PREPARATION.md records NVDA-oriented local commands, scope, explicit proof limits and a source-hash verification step.
- Scoped GitHub Actions test both platforms but the exact-head checks were still QUEUED, NOT GREEN when last inspected. Hardware qualification, licensed real table-closure, formal chess-Braille transliteration, lawfully usable source corpus, reader/device tests, OCR/eBraille and product integration remain unsatisfied.
- **SECTION 55: 0/16 independently DONE, terminal NOT DONE. Do not move to another section yet.**

## Third continuation checkpoint — local Liblouis dependency closure

- Added acs/chess_braille_tables.py: bounded recursive UTF-8 local Liblouis include scan, deterministic SHA-256 dependency closure, relative path evidence, cycles/escaped/symlink/invalid rules rejected; this is file-inventory assurance, NOT proof of actual compiled Liblouis semantics or standardized chess Braille notation.
- The generator now scans closure before and after translation, rejects any file drift, adds table_closure_sha256, table_closure_files, total_bytes and LOCAL_PIN_ONLY_NOT_LANGUAGE_CERTIFICATION to output manifest, then independently rechecks its unpublished package including live table.
- Public verifier tools/section55_verify_bundle.py supports optional --table-file to recheck exact transitive source dependencies against archived manifest.
- Added tests/test_section55_liblouis_tables.py and expanded local CLI tests for legitimate recursive includes, cycles/traversal/symlinks, unsupported binary files, changed nested dependency during/after generation, source/page/BRF consistency. Updated 2-OS scoped Actions.
- Fixed platform-native Path type rejection in verifier and multiline source/PGN blank-line PEF handling.
- A draft GitHub PR is not a released product; GitHub Actions jobs remained queued at the last observation, and real chess Braille codes, physical paper/embosser, publisher rights, independent reader proof, eBraille, OCR, full queue/product integration remain open. **0/16 DONE.**

## Fourth continuation checkpoint — bounded local batch queue

- Added tools/section55_batch.py, a local crash-replay-aware batch worker with a single immutable queue JSON revision (SHA-256), at most 32 jobs, at most 1–4 NEW jobs per invocation, unique safe job output folders, private exclusive worker lock, atomic and fsynced completion journal and exact SHA re-verification of any previously published output.
- The worker refuses changed source books, stale or altered Liblouis dependency closure, incomplete package, tampered journal, unknown job IDs, changed queue hash, concurrent lock and accidental overwrite. It can re-attach a package already published before a journal checkpoint. A stale crash lock requires manual process verification before removal.
- Added tests/test_section55_batch.py for bounded two-run processing, re-entry without duplication, crash between publication and journal, journal and queue tampering, damaged files, stale lock and unsafe job IDs. Updated GitHub Actions matrix and documented the exact commands in docs/section55/LOCAL_BATCH_RECOVERY.md.
- This is a local, offline batch prototype, not a production cloud agent; there are no paid model requests or assumed input/output model-token budgets. Physical, chess-code, licensing, proofreading, accessible UI, OCR/eBraille, real corpus and end-to-end qualifications remain open.
- Last authoritative status: Section 55 is ACTIVE / PARTIAL / NOT DONE; no subsections can be marked DONE from synthetic tests alone.

## Fifth continuation checkpoint — offline accessible HTML preview and two-OS evidence

- Source branch added acs/chess_braille_html.py: deterministic offline, source-readable HTML accompanying provisional PEF and optional BRF, with keyboard anchors/skip navigation, source headings/lists/chess/FEN and language metadata; Unicode Braille pages are flagged UNVERIFIED and aria-hidden to avoid exposing untranslated cells as source-readable text. Strict local CSP, source escaping and no remote resources or JavaScript.
- Generation CLI supports --emit-html; a public package may now contain a chess-book-unverified.html file. Quality-report.json records output_html_sha256, html_print_ready=false and source title override for reproducible Markdown/TXT export.
- Independent bundle verifier re-imports original canonical JSON or source TXT/Markdown using existing BookDocument importers, deterministically regenerates HTML from original text and pinned PEF and compares every byte. Batch journal optionally tracks html_sha256 and refuses output/substituted preview.
- Added tests/test_section55_chess_braille_html.py; extended local CLI/batch tests for source/PEF binding, HTML escaping, navigation/links, title overrides, tampering and resume. Expanded scoped dual-OS GitHub workflow.
- Confirmed earlier source SHA da7cf628c868a4b5a522ea62cb34e69488e4e439 Section-55 targeted CI completed SUCCESS on Ubuntu and Windows. This is a synthetic boundary gate ONLY. At later HTML source head c0eddf79d68146b87dcb667beb2d2ce770109274 dual-OS Actions were QUEUED and therefore NOT GREEN at observation.
- No official eBraille publication format is implied by the HTML preview. No certified physical print, standard chess code, lawfully sourced books with rights/reader acceptance or main integrated release exists yet. Section 55 still **0/16 terminal DONE**.

## Sixth continuation checkpoint — independently sourced UKAAF 2015 chess notation subset

- Consulted the published UKAAF *Braille Chess Code and Layout* (2015), official rule/profile accessible through British Braille Chess Association. URL: https://braillechess.org.uk/wp-content/uploads/2023/08/Braille-Chess-Notation.htm . Its sections 3.x (algebraic move notation), 5.1 (Forsyth six-dot position notation) and 5.2/6 (printed diagram/problem layout) are distinct acceptance domains.
- Added acs/chess_braille_ukaaf2015.py: clause-5.1 six-dot Forsyth position serializer strictly from canonical chesscore.Board, reversible decoder proving exactly 64 pieces/squares, published starting-position fixture, black/white distinctions, grouped empty ranks. Added a separately fail-closed narrow UKAAF 3.2–3.6 lexical algebraic SAN subset with published examples, *without* chess-move legality claims.
- Added **opt-in** --emit-ukaaf-diagrams for one-book output and emit_ukaaf_diagrams for bounded queue: source-owned Position/Diagram/Exercise nodes yield a SHA-pinned chess-diagrams-ukaaf2015-unverified.json. The verifier independently reconstructs the catalog from the original source and refuses even catalog+report double tampering. The batch journal tracks the extra digest.
- Added/expanded tests/test_section55_ukaaf2015_chess.py, tests/test_section55_local_cli_package.py, tests/test_section55_batch.py, and targeted two-OS workflow inputs. Documentation: docs/section55/UKAAF_2015_CHESS_STANDARD.md, LOCAL_BRAILLE_PREPARATION.md, LOCAL_BATCH_RECOVERY.md.
- Important mismatch: separate Liblouis en-chess.ctb subtable encodes chess Unicode figurines with dot 7, so it CANNOT be silently flattened into this six-dot UKAAF profile. This boundary is explicit and must be independently qualified.
- Before this wave, earlier targeted Section 55 CI on Windows/Ubuntu was SUCCESS for source sha da7cf628c868a4b5a522ea62cb34e69488e4e439. Later source/standards/head checks must be read by exact current sha, not inferred. Source draft PR branch was merged with then-current main via safe disjoint-file two-parent commit 51f2ebbc3c8b738eb6cb944bac9784cf7a7e7bdd (19 owned files preserved, no file overlap).
- **Terminal status still 0/16 DONE, NOT DONE.** UKAAF chess move code is incomplete, special chess layout/printed diagrams unimplemented, real Liblouis and device not qualified, official sample corpus/rights and blind-reader acceptance missing, eBraille/OCR/product release integration still open.

## Seventh continuation checkpoint — STRICT PGN legality guard before UKAAF move coding

- Added encode_ukaaf2015_canonical_mainline_pgn(pgn) as a bounded legal chess proof boundary: one STRICT parser-confirmed PGN, one mainline of at most 512 moves, no unresolved warnings/comments/NAG/variations; canonical chesscore.Board validates exact legal moves and computes authoritative SAN and before/after FEN, then only supported UKAAF algebraic subset is mapped.
- Unsupported but otherwise potentially legal castling, promotions and special printed annotations explicitly fail closed until formally qualified. This code NEVER invents chess rules or claims full published game layout.
- Added tests for legal e4/e5/Nf3/Nc6 sequence and expected six-dot UKAAF move cells; illegal repeated pawn move; variation/comment/NAG rejection; unsupported castling/promotion; oversized/multiple game rejection, exact FEN state.
- Docs updated: docs/section55/UKAAF_2015_CHESS_STANDARD.md. This is partial UKAAF clauses 3.2–3.6, not complete Part 55.4 or UKAAF 4.x formatting.
- Latest exact-source scoped Windows and Ubuntu CI were still QUEUED at observation; earlier dual-OS source da7cf628 PASS remains distinct. Terminal completion still **0/16 DONE**. No move to another section permitted yet.
