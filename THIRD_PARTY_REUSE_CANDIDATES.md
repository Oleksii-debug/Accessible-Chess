# Accessible Chess — third-party reuse candidates

Working engineering inventory; license compatibility must be verified per exact version.

- `asdfjkl/cbh2pgn`: MIT. High-value CBH/CBG decoder reference/brick. Upstream depends on GPL `python-chess` and does not convert annotations. Preferred route: adapt only MIT decoder logic behind our read-only ChessBase adapter and connect to our own GameTree/core, preserving MIT notice.
- `jhlywa/chess.js`: BSD-2-Clause. Strong future Web/PWA candidate for standard chess legality/FEN/PGN utilities.
- `mganjoo/gchessboard`: MIT. Accessible web-board candidate, but must pass our stricter NVDA/keyboard contract.
- `justinfagnani/chessboard-element`: MIT. Presentation candidate, accessibility audit required.
- `shaack/cm-chessboard`: code MIT; bundled piece assets have separate CC licenses and need asset audit.
- `lichess-org/lila`: AGPL-3.0-or-later. Prior art only unless we deliberately choose AGPL for the relevant combined server work.
- `lichess-org/chessground` and `lichess-org/pgn-viewer`: GPL-3.0-or-later. Do not embed into a closed-source web client.
- `niklasf/python-chess`: GPL-3.0-or-later. Excellent reference/test oracle, not default embedded dependency for a closed-source-capable distributed app.
- Scid/Scid vs PC/scidCommunity: GPL. Useful prior art and behavioral comparison, not copy-paste material for a closed-source-capable core.
- `official-stockfish/Stockfish`: GPL-3.0. Keep as separate UCI executable with required license/source obligations.
- ChessBase/Fritz/Chess.com proprietary product code: never copy. Use public behavior/APIs, lawful samples, specs and independently licensed readers/converters.