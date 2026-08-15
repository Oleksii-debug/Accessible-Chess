# Third-party component inventory

This file is a pre-integration inventory. `approved` means approved for technical evaluation, not automatically approved for production packaging. Every production component needs exact version pinning and required notices.

| Component | Purpose | License | Current decision | Integration mode |
|---|---|---|---|---|
| asdfjkl/cbh2pgn @ 42b3592738062db1f768239e85df1b98cb1cead9 | classic CBH/CBG decoder | MIT | approved for adaptation | source-derived decoder behind ChessBase adapter; remove GPL python-chess dependency |
| Stockfish | analysis/engine play | GPL | already used with obligations | separate UCI executable/process |
| SQLite | ACSDB/storage/search | public domain | approved/keep | standard runtime/library |
| jhlywa/chess.js 1.4.0 | browser chess rules/FEN/PGN | BSD-2-Clause | approved for Web/PWA evaluation | npm dependency behind browser chess service |
| shaack/cm-pgn | rich browser PGN | MIT | approved for Web/PWA/differential tests | npm dependency behind PGN adapter |
| mganjoo/gchessboard | browser board | MIT code; piece assets have separate CC BY-SA provenance | conditional | UI component only after NVDA/keyboard gate; prefer own assets |
| GoogleChrome/workbox 7.4.x | PWA/offline/service workers | MIT | approved for Web/PWA | build/runtime PWA tooling |
| mwilliamson/mammoth.js | DOCX to semantic HTML | BSD-2-Clause | approved as ingestion helper | source adapter -> sanitized HTML -> BookDocument |
| Mozilla PDF.js/pdfjs-dist | PDF parse/render | Apache-2.0 | approved as source helper | source adapter/viewer, not accessible book truth |
| FastAPI | Python backend/API/WebSocket | MIT | preferred backend candidate | infrastructure/API adapter around existing application core |
| Keycloak | OIDC/OAuth accounts/device authorization | Apache-2.0 | preferred identity candidate | separate identity service; no chess/billing logic inside |
| Colyseus | room/matchmaking/state sync | MIT | defer until scaling/room complexity | optional external multiplayer infrastructure |
| LiveKit server/SDKs | voice/video/data/classroom media | Apache-2.0 | preferred media candidate | separate media service + SDKs |
| coturn | TURN/STUN | BSD-style permissive | approved when self-host media needs TURN | separate infrastructure service |
| Lichess chess-openings data | ECO/opening names/positions | CC0 | approved data source | pinned data snapshot + provenance |
| Lichess Open Database exports | games/puzzles/evals/openings | CC0 | approved data source | selected pinned datasets + provenance |
| python-tuf | secure update metadata/client | MIT + Apache-2.0 | approved security candidate | update trust/verification layer |

## Excluded from embedding by default

| Component | Reason |
|---|---|
| lichess-org/lila | AGPL; use as architecture/API prior art only unless licensing strategy changes |
| lichess-org/chessground | GPL; repository explicitly states combined website distribution constraints |
| lichess PGN viewer | GPL; do not embed in proprietary web build |
| python-chess | GPL-3.0-or-later; not a default runtime dependency for closed-source-capable build |
| SCID/scidCommunity | GPL; use for behavior/test ideas, not copied code |
| ChessBase/Fritz/Chess.com proprietary implementation code | no permission to copy; only documented behavior, lawful samples/APIs/specs may be used |

## Production notice rule

Permissive source reuse does not require us to advertise another product in the main Accessible Chess UI. Required copyright/license notices belong in a `THIRD_PARTY_NOTICES`/About/Licenses area and in distribution documentation as required by each license. Accessible Chess remains our product and architecture; third-party code remains attributed as a component.