# Section 38 terminal closure

Status: **DONE — TERMINAL**

## Accepted authorities

- Canonical real-corpus and native Book ingress: PR #2517 candidate
  `69b233061bb6fa5544bc3de740d40852a963af7f`, dual-OS run
  `38010829671`, converged through PR #2541 candidate
  `443cbba0c8b3bbf442ff3ae4533e5d1fb5dc000e` and integrated as
  `4e96d414abebda580bed46d45f8e91182b45a51f` after dual-OS run
  `38011119187` succeeded.
- Final Section 38 convergence candidate: PR #2516 head
  `1d1481fc45e54b98a4821e2e8a0e3cd6ea56a517`.
- Exact-candidate Book/Board/Library qualification: runs `38012159724` and
  `38012159851`, Ubuntu and Windows jobs successful.
- Exact-candidate external-source qualification: run `38012248490`.

## Closed acceptance scope

### 38.1 — real games and archives

The accepted main ingress source-binds original PGN/EPD/FEN and Stockfish and
Lichess ECO inputs, checks expected hashes and counts, preserves annotations,
RAV/NAG, custom starts and Chess960 capability boundaries, refuses unsafe ZIP
members and source mutation, and exercises Library publication, export, reopen,
cancellation and restart.

### 38.2 — real books

Actual external Gutenberg TXT/HTML/EPUB3 sources and the native EPUB3 Book path
are exercised with source receipts.  The accepted DOCX path is an explicitly
derived interoperability document, not a falsely labelled independent
publisher original.  Missing images, tables or spine semantics remain
`PARTIAL_SEMANTIC_LOSS`.  Native PDF import and an independent lawful
third-party DOCX/PDF pair remain `UNSUPPORTED`/`BLOCKED`, not PASS.

### 38.3 — canonical references and recovery

FEN/SAN/GameTree/ACSDB identity, metadata, invalid input, source replacement,
cancellation, atomic publication, backup/restore, idempotent reimport and
restart are covered through the canonical application and storage owners.  No
second chess parser, rules engine or database authority was introduced.

### 38.4 — ChessBase-family observation

The existing canonical CBH path and the three genuine GPL libcbh families
(33 registered companions) remain the product authority.  The optional pinned
MIT cbvault backend was built and exercised only as an external clean-room QA
oracle.  Its real result is intentionally retained as `PARTIAL`/`BLOCKED`, with
zero support promotion and no bundled external binary or database.

The genuine Northwest Chess January 2013 CBV and parallel PGN were acquired in
the ephemeral hosted job and hash-observed.  The external CBV unpacker failed
closed, so the receipt remains `BLOCKED`; no fabricated decoded games, semantic
match or ACSDB restart PASS is recorded.  CBF+CBI, complete 2CBH and CBONE
remain unavailable and unsupported.  This is the required honest result of
practical testing, not a claim that those formats are implemented.

### 38.5 — source manifest and rights

The protected manifest/right-status work remains intact.  Direct sources,
hashes, acquisition class, expected/actual result and public-release boundaries
are separated.  Restricted or unproven third-party payloads are not shipped.

### 38.6 — product integration

Real material reaches canonical Library, Books, Training, Board, Search and
Windows/Web boundaries.  The final convergence includes the proven Book to
Board recovery import repair and the platform-neutral PGN compare-and-swap
publication race test.  Exact-head Books/Board/Library jobs passed on Ubuntu
and Windows.

## Executed verification

- Local focused Section 38 and inherited boundary set: 125 tests PASS, 3
  external-corpus-only tests skipped because the local checkout deliberately
  lacks that external corpus; `acs.selftest` PASS.
- PR #2516 focused pre-convergence set: 55/55 PASS.
- PR #2517 real-corpus integration: `38010829671` Ubuntu + Windows SUCCESS.
- PR #2541 current-main candidate: `38011119187` Ubuntu + Windows SUCCESS.
- PR #2516 Book/Board/Library candidate: `38012159724` and `38012159851`
  Ubuntu + Windows SUCCESS.
- PR #2516 external CBH/CBV observation: `38012248490`; the job succeeds only
  when PASS/PARTIAL/BLOCKED receipts are internally consistent and fail closed.

Physical owner/NVDA acceptance is not claimed.  Under Simplified Closure v3 it
belongs to final whole-product acceptance, not this intermediate Section.

## Terminal lock

Ordinary workers must skip Section 38.  Reopen only after recording a concrete
regression, invalid closure evidence, materially changed acceptance contract or
later integration break.  A newly found lawful source can extend future format
support without invalidating this truthful terminal observation by itself.

