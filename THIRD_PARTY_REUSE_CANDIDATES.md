# Accessible Chess — third-party reuse candidates

This file is a working engineering inventory, not a final legal determination.

## Immediate candidates

### asdfjkl/cbh2pgn
- Purpose: read classic ChessBase `.cbh`/`.cbg` family and convert games to PGN.
- Upstream license: MIT.
- Current upstream limitations: standard games only; moves/variations and selected metadata; no game annotations; README reports performance limitations.
- Important dependency: upstream uses `python-chess`, which is GPL-3.0-or-later.
- Accessible Chess strategy: evaluate the MIT decoder logic as a read-only adapter brick, but connect it to our own chess/GameTree layer rather than adding `python-chess` to a closed-source-capable build. Preserve MIT notice. Validate on user-provided samples. Never claim fields upstream does not decode.

### jhlywa/chess.js
- Purpose: browser-side standard chess legality, FEN/PGN utilities.
- License: BSD-2-Clause.
- Accessible Chess strategy: strong future Web/PWA candidate behind an application adapter; do not make the web client the authoritative source of domain state.

### mganjoo/gchessboard
- Purpose: accessible/customizable dependency-free web chessboard component.
- License: MIT.
- Accessible Chess strategy: evaluate for future Web/PWA only after NVDA/keyboard semantics testing against our stricter board contract.

### justinfagnani/chessboard-element
- Purpose: web chessboard component.
- License: MIT.
- Accessible Chess strategy: possible presentation brick, subject to accessibility audit.

### shaack/cm-chessboard
- Purpose: dependency-free SVG chessboard.
- Code license: MIT.
- Asset warning: bundled piece sets use separate Creative Commons licenses; audit assets before reuse.

## Projects useful as prior art but not direct closed-source bricks without a licensing decision

### lichess-org/lila
- License: AGPL-3.0-or-later.
- Use: architecture, behavior, protocol and test ideas; do not copy into a closed-source backend.

### lichess-org/chessground
- License: GPL-3.0-or-later.
- Upstream explicitly says a combined website using it must be GPL.
- Do not embed into a closed-source web client.

### lichess-org/pgn-viewer
- License: GPL-3.0-or-later.
- Upstream explicitly says combined website work must be GPL.
- Do not embed into a closed-source web client.

### niklasf/python-chess
- License: GPL-3.0-or-later.
- Excellent reference/test oracle for chess legality/PGN/UCI, but direct import into a distributed closed-source Python application is not the default strategy.

### Scid / Scid vs PC / scidCommunity
- License: GPL.
- Useful prior art for chess database UX/search/import behavior and test corpora where permitted, not copy-paste material for a closed-source-capable core.

## Separate executable

### official-stockfish/Stockfish
- License: GPL-3.0.
- Integration: keep as a separate UCI process. Distribution must include/preserve the GPL notice and corresponding-source/source-pointer obligations for the exact binary distributed.

## Proprietary products

ChessBase, Fritz and similar commercial proprietary programs are not sources to copy. Use documented public behavior, supported APIs/protocols, legally obtained test files, and independently licensed readers/converters. Never paste proprietary implementation code into Accessible Chess.