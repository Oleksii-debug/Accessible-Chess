# Section 39 terminal closure

Date: 2026-10-09  
Protocol: Simplified Closure Protocol v3  
Status: **DONE — TERMINAL**

## Accepted authority

- Canonical repair PR: #2509.
- Exact tested candidate: `36308ecf7efaec28cee79c5d91fa66de37de5578`.
- Explicit integrated Product/evidence line: PR #2494 merge
  `ce771376f8269b174d6a30c991295816d00fece7`.
- The tested candidate is an ancestor of the integration merge and the two
  trees have zero file delta.
- The repair preserved the protected Section 39 implementation already on
  PR #2494 and added only qualification fixes found by executed tests.

## Executed acceptance

The following ran on the exact candidate, without skipped checks being counted
as success:

1. `python -m unittest discover -q -s tests -p 'test_section39*.py'`:
   **59/59 PASS**.
2. The selected adjacent format, bilingual Books/application, Stockfish,
   ChessBase source-policy, decoder and family-integrity suite:
   **99/99 PASS**.
3. Pinned upstream `rolandlo/libcbh` source commit
   `9641c5c3949d8fb210b17dd9aa54455645843696`: **PASS**, 3/3 genuine
   source families and 33/33 registered original companion files.

The closure run found and repaired four concrete faults before acceptance:

- generated EPUB/DOCX ZIP members did not have deterministic metadata;
- malformed packaged-source receipts leaked the lower-level collection error;
- the pinned real libcbh fixture includes a non-consumed `.cbtt` title-tree
  cache, while unknown unregistered `.cb*` members still must fail closed;
- one application test confused the Book-open warning count with the number of
  document blocks.

## Canonical 39.1–39.6 result

The acceptance surface now enforces all of the following:

- exactly sixteen format identities: FEN, SAN, EPD, PGN, ACSDB, EPUB, HTML,
  TXT, Markdown, DOCX, PDF, CBH, CBV, CBF, 2CBH and CBONE;
- separate READ, WRITE, ROUNDTRIP and overall qualification results, including
  honest PARTIAL, BLOCKED and UNSUPPORTED outcomes;
- comments, NAGs, nested variations, Chess960/FRC, Unicode/encoding,
  diagrams, bounded large/corrupt input, missing multifile companions,
  cancellation, atomic recovery and restart;
- import → open/read → navigation → search/edit → export → reimport → semantic
  comparison, with losses recorded rather than hidden;
- original-byte, derived and mock/test evidence separation with source ID,
  SHA-256/Git blob, importer, expected/actual outcome, code SHA and CI-readback
  joins;
- 800 independent capability cells and packaged archive/product readback;
- CBH-family PASS only when the real pinned family and independent semantic
  oracle boundaries succeed.

Unsupported functionality is not fabricated to close this testing section.
CBF, 2CBH, CBONE, native PDF import and any unavailable proprietary operation
remain explicitly BLOCKED or UNSUPPORTED. That truthful classification is the
required terminal outcome of Section 39, whose scope is practical testing of
all formats and variants—not an instruction to invent format support.

## Evidence boundary

Hosted jobs that were queued or unavailable at closure are not described as
green. No paid compute was used. Physical Windows/NVDA confirmation remains a
single final whole-product acceptance gate under protocol v3; it is not an
intermediate Section 39 blocker. No known failing repository-controlled
Section 39 check remains.

## Lock

Do not reopen Section 39 for ordinary follow-up work. Reopen it only after a
concrete regression, invalid closure evidence, a materially changed acceptance
contract or a later integration break is recorded as `REOPENED`.
