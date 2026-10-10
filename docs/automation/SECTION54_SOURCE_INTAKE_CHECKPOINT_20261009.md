# Section 54 — bounded source intake implementation checkpoint (2026-10-09)

## Exact scope

This checkpoint targets foundational slices of **54.1** and **54.11** only. The parent **Section 54 is PARTIAL / NOT DONE**. No 54 subsection is declared terminal at this checkpoint. Section 51 is not touched.

New additive source: `acs/format_factory_intake.py` and `acs/format_factory_tokens.py`; regression tests: `tests/test_section54_source_intake.py` and `tests/test_section54_factory_tokens.py`; dedicated Ubuntu/Windows workflow: `.github/workflows/section54-source-intake.yml`.

Implemented capability: immutable in-memory source-byte SHA-256 and bounded identity, extension-content mismatch denial, conservative MIME/signature detection of PDF, JPEG, PNG, ZIP/EPUB/DOCX, PGN and structured text. ZIP metadata rejects traversal, duplicate names, special-file entries, encrypted entries, individual/aggregate size overruns and extreme expansion. EPUB container identification does not claim successful EPUB content parsing. Supported TXT/Markdown, HTML, EPUB are delegated to existing BookDocument importers; no alternative chess parser, FEN authority, text converter, or privileged filesystem/network activity is introduced.

54.11 partial: immutable per-run independent INPUT/OUTPUT token envelopes; strict provider output-cap preflight; reservation across concurrent jobs; actual/cached/reasoning usage accounting by model; unknown-billing and overshoot blocking, pre-dispatch cancellation. This is a reusable boundary only: not yet wired to ModelGateway/UI, no durable account usage service, no live provider call, no actual in-flight hard interruption claim. No monetary or monthly budgets.

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
- 54.9–54.12: per-book durable queues, integrate the token governor into actual ModelGateway and persistent runs, idempotent checkpoints, provider response reconciliation and recovery.
- 54.13–54.15: privacy, QA of real lawful books, Windows/Web product integration, acceptance, final shipping provenance.

## Verification and integration rule

The committed tests cover deterministic source identification, digest, canonical import reuse, archive traversal and duplicates, forged extensions, malformed EPUB/ZIP, unsupported formats, privacy-preserving path display, concurrent token reservations, duplicate IDs, model-level usage and unknown-billing recovery lock. **Presence of tests is not evidence of their execution.** Do not call tests PASS before a completed exact-head CI or actual local execution. No authenticated external source was transmitted; no paid API was called. Preserve Sections 0–53 accepted work and 55 separately. After qualification, converge only through the canonical main release path. No DONE without whole 54 acceptance.


## Continued implementation, 2026-10-09 (owner "continue" command)

This same Section 54 finisher lineage now also has:

- \`acs/format_factory_policy.py\` plus \`tests/test_section54_factory_policy.py\`: immutable book-specific scope, numbered noncontiguous selector ranges, printed-versus-file-page distinction, seven deterministic Ukrainian command patterns, ambiguous intent fail-closed, output-format policy, explicit provider/model consent and per-run INPUT/OUTPUT caps, stable source/policy SHA-256 identity. Not a model-driven live agent or user UI.
- \`acs/format_factory_queue.py\` plus \`tests/test_section54_factory_queue.py\`: local SQLite WAL job ledger supplied with trusted per-user database location, durable WAITING/RUNNING and lease/heartbeat recovery, priority selection, worker-fencing after crash or expiry, immutable policy fingerprint, idempotent per-fragment acknowledged evidence, and conditional internal job DONE requiring verified fragments, declared coverage and output hash. This is a **new Section 54-specific job adapter**, not a replacement for existing application persistence, nor yet connected to app backup/restore.
- \`acs/format_factory_export.py\` plus \`tests/test_section54_factory_export.py\`: private in-memory HTML and TXT output from canonical \`BookDocument.as_dict()\` with structural headings/lists, copyable PGN/FEN, escaped HTML, source/output SHA-256, explicit loss flags and no public release authorization. PDF/EPUB/DOCX/PGN/ACSDB creation remains **unimplemented**. TXT heading/list output and original diagram images are marked lossy, and strict output refuses loss.

Local isolated deterministic tests in a lightweight development harness (using a **simplified stand-in BookDocument**, not the real canonical package) executed **21/21 PASS**, covering policy, concurrency/crash/SQLite leases and HTML/TXT output logic. The stand-in is **not committed** and these are **not canonical integration tests**. For the queue/policy modules, GitHub code/test content mirrors the isolated local-tested bytecode. The real \`acs.bookdocument\` and canonical importer integration is validated only once hosted exact-head CI genuinely executes. The workflow matrix targets Ubuntu 22.04 and Windows 2025; a QUEUED/PENDING run is explicitly **NOT PASS**. A PR is not DONE.

### Current closure truth

Parent Section 54: **PARTIAL, NOT DONE**. No subsection is terminal DONE. Existing code covers **bounded portions** of 54.1, 54.6, 54.8, 54.9, 54.10, 54.11, 54.13; all full 54.1–54.15 clauses require final integration/qualification. Section 51 and 55 untouched. Outstanding blockers: approved PDF/DOCX/OCR/multimodal and ChessBase actual import; author/edition/source-page anchoring; canonical per-variation legality and edition provenance; lawful search and model orchestration; keyboard/NVDA policy surface; tagged PDF/EPUB3/PGN output; real provider token settlement and durable API usage; app backup/upgrade integration; exact Windows/Web user journey; real corpus, security/rights acceptance and release provenance. Never promote partial code into full-feature DONE or privately publish copyright-protected books.


## 54.7 form update, same active partial lineage

New \`web/format_factory_policy_form.js\` and \`tests/js/format_factory_policy_form_test.js\`: isolated, user-facing keyboard form collecting requested book coverage, noncontiguous page/chapter ranges, output format, language, separate search/AI consent and exact per-run input/output token caps. Label-to-control associations, accessible status, focus recovery, safe submit, and blocked unsupported outputs are covered by a runnable local Node fake-DOM contract PASS. The form is NOT YET mounted inside actual Windows/WebView or a canonical backend action: functional release acceptance and human NVDA validation are not claimed. An exact integer guard avoids JS 2^53 rounding of token limits. Output offers only private HTML/TXT previews until other formats are qualified.

Latest exact branch SHA must be obtained from GitHub PR #2530 live head; older checkpoint SHAs are not final. GitHub Actions for Section54 and adjacent product workflows were QUEUED, not SUCCESS at the last read. \`PARTIAL/NOT DONE\` remains the only truthful parent status.

## Continuation — PGN semantic-book bridge and XHTML source precision (2026-10-09)

The existing draft PR #2530 was **reused**; no competing factory branch, parser or duplicate PR was created. Files changed on this lineage:

- `acs/format_factory_intake.py`: recognize XHTML with XML declaration, common fragment HTML and leading HTML comments while rejecting generic XML disguised with an XHTML extension; added `pgn` to strict BookDocument ingress only when the canonical parser accepts it.
- `acs/format_factory_pgn_book.py`: new bounded adapter calls canonical `parse_pgn_bytes(strict=True)` and `serialize_game` to create one semantic Book `Game` block per PGN game. Each block retains parsed annotations, comments, tags and variation structure in canonical PGN, a stable digest-based identity, and an ordered source anchor. If any game is invalid the import fails atomically; no improvised SAN parser, OCR, license grant or independent ChessCore/Board authority is introduced.
- `tests/test_section54_source_intake.py`: three XHTML/HTML/generic-XML negative/positive regressions; existing PGN intake expectation strengthened to actual one-game BookDocument import.
- `tests/test_section54_factory_pgn_book.py`: six real canonical adapter tests (multi-game, source integrity, comment/variation serialization, HTML escaping, strict corrupt SAN failure, invalid source and determinism). No fake BookDocument stub is used in these new tests.
- `.github/workflows/section54-source-intake.yml`: includes the new route and test in both Windows and Ubuntu compile/test gates.

**Capability amendment:** Strict canonical PGN collections are now a PARTIAL semantic book-ingress implementation, not merely signature detection. This is a book-of-games bridge, **not** a finished AI format factory. Section 54.4 per-position legality/source verification is still NOT DONE: PGN parser structural validation alone must not be labeled proof that a game position matches the original book. Multi-format PDF/DOCX/OCR, external lawful source matching, real EPUB/PDF rendering, durable integrated product UI, and NVDA remain outside this bounded change.

**Evidence:** Source/tests/workflow have been committed to PR #2530. The latest exact-head Section54 workflow has Windows and Ubuntu jobs **QUEUED** at the time of this checkpoint; **no executed hosted test PASS is claimed**. The existing earlier 21 local tests do not qualify these newly committed changes. No subsection, parent Section 54, or Section 55 is marked DONE. Verify actual CI conclusions on the precise new PR head before treating this as qualified or merging. Preserve all original Section54 source/test blobs and original baseline Sections 0–53.


## Continuation 2026-10-09 22:21Z owner command

Owner explicitly instructed: continue Section 54 and only after full closure proceed to next not-DONE Section. **Section 54 is still PARTIAL, 0/15 subsections independently verified DONE.**

Source-intake correction: original \`_sniff_text\` contained doubly escaped raw-regex whitespace/boundary tokens, misclassifying real HTML/XHTML as plain text and rejecting the extension. Corrected \`acs/format_factory_intake.py\` and real newline fixtures plus new HTML doctype/semantic fragment tests in \`tests/test_section54_source_intake.py\`.

New real-canonical private conversion layer: \`acs/format_factory_conversion.py\`, \`tests/test_section54_factory_conversion.py\`. Verified source digest must match immutable approved policy; only original-language preview, no silent translation, no external search/model execution. Canonical importer -> \`BookDocument.as_dict()\` -> explicit chapter scope -> output adapter; uncertain page/edition mappings abort. Chapter selection requires explicitly selected semantic heading level (never guess title as Chapter 1). Multiple requested formats return atomically in memory only after all succeed. No public release authorization. Strictly rejecting nonimplemented DOCX/tagged PDF/PGN/ACSDB outputs.

New deterministic private EPUB3 candidate: \`acs/format_factory_epub.py\`, \`tests/test_section54_factory_epub.py\`. Creates standards-shaped mimetype-first ZIP, OPF metadata/manifest/spine, accessible XHTML chapters and nav TOC, internal XML validation, SHA256, content-unique selection/edition identifier, stable supplied \`modified_utc\`, explicit loss flags. Canonical EPUB importer readback is now asserted in tests. **EPUBCheck, DAISY/NVDA real-user review, genuine licensed corpus and app integration have NOT been qualified; the UI still disables EPUB3 pending qualification.**

Shared-branch addition independently identified and preserved: \`acs/format_factory_pgn_book.py\` and \`tests/test_section54_factory_pgn_book.py\` extend canonical PGN-to-BookDocument ingress. Do not overwrite or supersede that worker's implementation. It remains a book-reading bridge, not Section 54.4 legality certification.

Durability queue hardening: \`acs/format_factory_queue.py\` gained owner-authorized resume from PAUSED/REVIEW_REQUIRED/PARTIAL tied to exact policy fingerprint. Even internal job DONE now requires explicit exact set of expected semantic fragments matching all verified checkpoints and an output SHA. Tests expanded. This does not certify a complete book or parent Section DONE.

No new native Windows/Web shipping integration or live provider call. Tests committed to \`.github/workflows/section54-source-intake.yml\` (Ubuntu/Windows), but latest exact-head Section 54 workflow was QUEUED as of readback, not PASS. \`main\` moved independently since branch fork; reconcile/rebase selectively only after verifying current source ownership. Preserve all other workers and baseline DONE sections. Next action: resolve exact-head CI failures if runners become available, then implement actual user-visible host integration, qualified EPUB/PDF/DOCX/PGN exports and licensed corpus/NVDA evidence.


### Repeated independent local smoke checks for exact GitHub blobs

At local path \`/mnt/data/section54_local\`, the local \`acs/format_factory_queue.py\` and \`tests/test_section54_factory_queue.py\` both had SHA1 Git blob IDs matching the current GitHub branch copies: **8/8 Python unittest queue cases PASS** for current owner-resume / exact-fragment-coverage implementation; lightweight \`acs.bookdocument\` stub was present but not exercised in queue.

\`acs/format_factory_epub.py\` local Git blob = **6af1bf9f4fbd74da8e0b3d94b6ddcab06adfc2f1**, identical to GitHub. Python compilation PASS, isolated in-memory BookDocument-stub EPUB smoke PASS: mimetype-first ZIP, XML parsing of each packaged document, escaped untrusted chapter text, byte-identical same-source same-timestamp output, distinct edition metadata IDs for different selected contents, three invalid modification dates rejected, original diagram graphics loss cannot pass without explicit acceptance. **These are local implementation smoke checks, not a canonical BookDocument integration or EPUBCheck/DAISY release grade, and not a Windows/NVDA functional acceptance.**

Latest exact-head qualification and release gates remain required. Do not infer any 54.x DONE from these bounded checks.


## 2026-10-10 — Windows raw ZIP hardening and private DOCX preview

**CI forensic result at previous exact source SHA 659e87ca09eeb29c038d9e86de26fe51d8288b38:** Ubuntu-22.04 Section 54 tests **68/68 PASS**, Windows-2025 **67/68 PASS, 1 FAIL**, in \`test_traversal_and_duplicate_archive_names_rejected\`; full workflow conclusion FAILURE. At the next SHA facc2... with a crafted raw ZIP path fixture, Windows still failed because \`zipfile.ZipInfo.filename\` on Windows **silently normalizes a malicious raw backslash path to slash** before caller path validation. The actual security fix in \`acs/format_factory_intake.py\` reads \`ZipInfo.orig_filename\`, refuses unexpected normalization and validates original names for backslashes, traversal and NUL. Added platform-independent raw central/local ZIP name tests for backslash and NUL to \`tests/test_section54_source_intake.py\`. The latest full CI must requalify this hardening; earlier Linux successes are not sufficient.

Added \`acs/format_factory_docx.py\`, \`tests/test_section54_factory_docx.py\`, and integrated DOCX into \`acs/format_factory_conversion.py\` + \`tests/test_section54_factory_conversion.py\` and \`.github/workflows/section54-source-intake.yml\`. It generates **private, in-memory reproducible DOCX preview** using direct bounded OOXML: validated source-identical BookDocument, actual paragraph and heading styles, speech language \`w:lang\`, independent ordered/bullet list numbering with explicit \`startOverride\`, preserved plain PGN/FEN and warnings for diagram fidelity, variation-tree navigation, and exercise-answer disclosure. OOXML, package relationships and deterministic edition identity are covered by targeted test assertions. Requires explicit qualified language, provenance source SHA and UTC modified date; illegal XML Unicode is rejected. Does **not** claim Word visual rendering, NVDA acceptance or tagged PDF/print-ready accessibility. \`web/format_factory_policy_form.js\` still disables DOCX until release qualification. Both input and output remain local/private and do not silently authorize copyrighted publication.

Other Section54 worker added private PGN chess-audit changes and tests to same branch; preserve them, do not take ownership or duplicate. This is **one parent Section 54 lineage; PARTIAL, 0/15 complete DONE**, pending successful exact-head CI on Windows/Linux and real app/Web/Word/NVDA and rights acceptance. Parent Section51 untouched.


## 2026-10-10 offline keyboard/CLI preview workflow (additive, not shipping)

New \`acs/format_factory_cli.py\` + \`tests/test_section54_factory_cli.py\`: a local, keyboard-invocable Python module providing a restricted **private offline** source-verified pipeline from one absolute non-symlink input file into existing absolute private output directory. User provides original language, one or more choices among HTML/TXT/EPUB3/DOCX, optional exact chapter mapping and explicit provenance modification timestamp for OOXML/EPUB. All operations call canonical \`FactoryJobPolicy\` and \`convert_factory_book_private\`, perform no network/AI usage, and reject unqualified OCR/PDF/external API paths. Existing outputs cannot be silently replaced. A completed result is staged and made visible with exclusive hard-link publication from fsynced same-volume temporary files; failures attempt cleanup, while caller must not assume a multi-file transaction is fully crash-atomic. The generated \`manifest.json\` includes source/policy SHA256, per-format result SHA256 and semantic losses with \`public_release_approved=false\` and \`PARTIAL_PREVIEW_ONLY\`.

Seven focused integration tests exercise private HTML and manifest, duplicate no-overwrite, unqualified PDF failure, explicit chapters, absent chapter, private EPUB+DOCX bundle, and missing timestamp. Included in exact-head Ubuntu/Windows CI. This CLI **does not mean Section 54.7 DONE**: it has not been manually validated with Windows NVDA, has no user-facing graphical app integration, no premium agent, and private products have not completed independent accessibility/render/rights acceptance. Do not promote the entire 54 section to DONE. Section 54 owner successors should run \`python -m acs.format_factory_cli --help\` and qualification CI before claiming this slice usable.
