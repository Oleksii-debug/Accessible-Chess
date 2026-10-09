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
