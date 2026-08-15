# Accessible Chess — reuse-first acceleration blueprint

Status: research/pre-integration. This document is the vetted source catalog for accelerating the proprietary Accessible Chess product without turning external projects into the product architecture.

## Decision rule

Before writing a mature generic capability from scratch, prefer a tested permissively-licensed component when adoption is smaller and safer than new implementation. External code must sit behind Accessible Chess ports/adapters. Preserve upstream notices. Never copy proprietary ChessBase/Fritz/Chess.com implementation code. GPL/AGPL components are not embedded into the closed-source-capable combined product without an explicit licensing decision.

## Immediate desktop/data reuse

### ChessBase CBH/CBG

Candidate: asdfjkl/cbh2pgn
Pinned upstream commit: 42b3592738062db1f768239e85df1b98cb1cead9
License: MIT
Use: decoder prior implementation and source material for classic CBH/CBG moves/variations and selected metadata.
Known upstream limits: standard chess only; no Chess960; annotations are not converted; upstream uses GPL python-chess.
Integration decision: adapt the MIT binary-decoder portions behind our read-only ChessBase adapter and map output to Accessible Chess GameTree/chess core. Do not import python-chess into the closed-source-capable runtime merely to use this decoder. Preserve MIT notice and exact upstream provenance. Differential-test against lawful/user-provided CBH/CBG samples and existing ChessBase/PGN exports.
Priority: P0/P1 after current Stage-1 integration debt is closed.

### PGN

Current Accessible Chess GameTree already preserves tags, comments, NAGs, nested RAV and multi-game structure. Do not replace it merely because external parsers exist.
Candidate for web and differential testing: shaack/cm-pgn
License: MIT
Use: browser-side rich PGN parsing/rendering and an independent oracle for variations/comments/SetUp/FEN/multi-game behavior.
Decision: reuse for Web/PWA or differential tests; migrate desktop parsing only if tests prove a clear reduction in code/defects.

### Local database/search

Component: SQLite
License/status: SQLite deliverable code is public domain.
Decision: keep ACSDB on SQLite; use SQLite indexes/FTS capabilities instead of inventing a custom storage engine. Do not rewrite working ACSDB.

### Chess engine

Component: Stockfish, external UCI executable.
Decision: keep separate process/UCI adapter; do not write an engine. Preserve Stockfish GPL distribution obligations independently from proprietary Accessible Chess code.

## Web/PWA reuse

### Browser chess rules

Candidate: jhlywa/chess.js
Version evaluated: 1.4.0
License: BSD-2-Clause
Capabilities: move generation/validation, FEN, PGN, check/checkmate/stalemate/draw.
Decision: strong default for browser-side validation/UI responsiveness. The server remains authoritative for online games. Do not duplicate the desktop Python core into handwritten JavaScript.

### Browser chessboard

Primary candidate: mganjoo/gchessboard
License: MIT
Capabilities: Web Component, click/drag/keyboard interaction, rudimentary screen-reader support, dependency-free.
Decision: evaluate against our stricter NVDA/keyboard/semantic-board contract. Reuse rendering/pointer/keyboard mechanics only if the accessibility gate passes; our semantic layer and Action Registry remain authoritative.
Asset warning: included piece SVGs are derived from Cburnett/Wikimedia and have separate CC BY-SA attribution requirements. We may use our own piece assets to simplify production notices.

Secondary candidate: justinfagnani/chessboard-element, MIT. Use only if accessibility testing beats gchessboard; Shadow DOM semantics need scrutiny.

Do not embed Lichess Chessground in a closed-source website: Chessground states GPL-3.0-or-later and says combined website work may only be distributed under GPL.

### Rich PGN in browser

Candidate: shaack/cm-pgn, MIT.
Decision: strong candidate paired with chess.js for comments, NAGs, nested variations, SetUp/FEN, Chess960 and multi-game lists.

### PWA/offline

Candidate: GoogleChrome/workbox
License: MIT
Decision: use for service worker generation, caching and resilient/offline shell rather than hand-writing service-worker machinery.

### DOCX book ingestion

Candidate: mwilliamson/mammoth.js
License: BSD-2-Clause
Capabilities: semantic DOCX-to-HTML conversion, headings/lists/footnotes/images/comments and style maps.
Decision: strong ingestion helper for Web/PWA book import, but never substitute its raw output for Accessible Chess BookDocument. Sanitize untrusted converted HTML and map chess semantics into BookDocument.

### PDF source support

Candidate: Mozilla PDF.js / pdfjs-dist
License: Apache-2.0
Decision: use for web PDF parsing/rendering/source-page inspection, not as the accessible book representation. Accessible linear reading still comes from BookDocument.

### EPUB source support

Candidate: epub.js
License: BSD-family permissive license; pin exact release/license before inclusion.
Decision: likely reader/import helper, behind BookDocument adapter.

## Web/backend/account reuse

### Backend API

Candidate: FastAPI
License: MIT
Decision: preferred first backend because Accessible Chess desktop/domain logic is Python. It minimizes duplicate chess logic and can expose REST/WebSocket endpoints around the same application contracts. Do not create a Node backend solely because web client is TypeScript.

### Authentication and desktop activation

Primary candidate: Keycloak
License: Apache-2.0
Capabilities: mature OIDC/OAuth identity server; supports OAuth 2.0 Device Authorization Grant.
Decision: strong default for accounts, login, desktop device activation, organizations/roles and OIDC. Accessible Chess still owns commercial entitlement policy and BillingProvider abstraction; Keycloak handles identity, not chess rules or billing truth.

Alternative: Ory/other headless IAM only if deployment/accessibility/admin complexity is materially lower after proof-of-concept.

### Multiplayer

First implementation decision: use server-authoritative game state through our Python application service plus WebSocket endpoint; this maximizes reuse of existing core.
Candidate for later scale: Colyseus, MIT, with authoritative rooms, matchmaking, reconnection and state synchronization.
Decision: do not introduce a second authoritative chess rules implementation just to use Colyseus. Evaluate it when matchmaking/room scaling becomes the bottleneck.

## Voice/video/classroom reuse

Primary candidate: LiveKit
License: Apache-2.0 for the server and major SDKs/components evaluated.
Capabilities: self-hosted or cloud WebRTC SFU; audio/video/data; JWT room permissions; browser/mobile/desktop SDKs; screen sharing; E2EE support in clients.
Decision: use LiveKit rather than building a TeamTalk-like WebRTC media stack from scratch. Build Accessible Chess classroom semantics, roles, chess synchronization and NVDA controls around LiveKit.

NAT traversal candidate: coturn
Role: TURN/STUN server.
Decision: use with self-hosted media only where needed; do not implement TURN/STUN ourselves.

Alternative full conferencing stack: Jitsi, Apache-2.0. Keep as fallback; LiveKit is currently the cleaner component-level fit.

## Training/opening data reuse

Lichess opening-name dataset: CC0/public-domain dedication. Use for ECO/opening names and known positions after pinning a snapshot.
Lichess Open Database exports: CC0; games, puzzles, evaluations and openings may be used commercially. Use selected snapshots for training/puzzle/opening datasets rather than inventing all training content.
Do not copy Lichess application code merely because its data is CC0. Lila is AGPL.

## Update/security reuse

Candidate: The Update Framework (TUF), python-tuf dual MIT/Apache-2.0.
Decision: use TUF concepts/library for signed update metadata and compromise-resistant update verification rather than inventing an updater trust model. Windows package installation remains our own release layer.

Candidate: WinSparkle for Windows update UX; verify exact current license/version before adopting. It may be useful as transport/UI, while TUF-style signed metadata remains the trust layer.

## Components not to embed in proprietary build by default

- Lichess lila: AGPL-3.0-or-later — architecture/protocol prior art only unless product licensing strategy changes.
- Lichess Chessground: GPL-3.0-or-later — do not embed in closed website.
- SCID/scidCommunity: GPL — behavior/testing prior art, not copied code.
- python-chess: GPL-3.0-or-later — do not add as a linked/imported dependency to the closed-source-capable runtime without explicit licensing decision.
- Proprietary ChessBase/Fritz/Chess.com code — never copy.

## Adoption order for fastest product completion

1. Do not interrupt the current Stage-1 integration and fresh Windows candidate gate.
2. Adapt pinned MIT cbh2pgn decoder logic to our own core after current integration is green; this is the largest immediate data-side time saver.
3. Keep SQLite, Stockfish and current tested GameTree rather than rewriting working subsystems.
4. When Web/PWA work begins, start from chess.js + cm-pgn + Workbox and evaluate gchessboard under our accessibility tests.
5. Start backend from FastAPI + Keycloak device/account flow; do not write auth protocols from scratch.
6. Add multiplayer through server-authoritative existing core; add Colyseus only if room/matchmaking complexity justifies it.
7. Add voice/video/classroom with LiveKit + coturn; never build raw WebRTC SFU/TURN from scratch.
8. Use Mammoth/PDF.js/EPUB helpers as source adapters into BookDocument.
9. Seed openings/training from CC0 Lichess datasets, with pinned snapshots and provenance.
10. Secure production updates with TUF-based signed metadata and code signing.

## Non-negotiable acceptance

A reused component is accepted only when: exact version/commit and license are recorded; required notices are present; security/dependency scan is known; regression/differential tests pass; accessibility is not degraded; it stays behind the appropriate port/adapter; and it reduces total work compared with maintaining our own implementation.