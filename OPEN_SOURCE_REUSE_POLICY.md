# Accessible Chess — reuse-first open-source policy

Do not reimplement mature generic chess infrastructure when a well-tested, license-compatible component can be adopted safely. Reuse must reduce delivery time and defect risk without sacrificing NVDA accessibility, modular boundaries, data fidelity, security, or the option to distribute Accessible Chess as a closed-source/commercial product later.

Before implementing a generic capability from scratch, perform a bounded reuse scan: candidate/version; license; maintenance/tests; architecture/accessibility fit; data-loss limitations; safest adoption mode.

Preferred embedded-code licenses: MIT, BSD, Apache-2.0, ISC and similarly permissive licenses, with required notices preserved.

GPL/AGPL code must not be copied, linked, imported, bundled into the same combined work, or used as a web component without an explicit repository-level licensing decision. GPL/AGPL projects may be studied for public interfaces, behavior, tests, protocols and architecture. Stockfish remains a separate UCI executable with GPL distribution obligations for the exact binary.

Never copy proprietary ChessBase/Fritz/Chess.com implementation code. Use documented behavior/APIs, user-provided lawful samples, public specifications and independently licensed readers/converters.

Immediate candidates: evaluate `asdfjkl/cbh2pgn` MIT decoder logic for CBH/CBG behind our read-only adapters, but do not pull its GPL `python-chess` dependency into a closed-source-capable build; connect adapted MIT decoder pieces to our own neutral GameTree/core and preserve attribution. For future Web/PWA, `chess.js` BSD-2 is a strong legality/FEN/PGN candidate. Evaluate permissive board widgets such as `gchessboard` MIT or `chessboard-element` MIT only if they pass our stricter NVDA contract. Do not embed Lichess Chessground/PGN Viewer into a closed-source web client because they are GPL.

Maintain a third-party inventory with upstream, exact version/commit, license, integration mode, local usage, notices/source obligations and security/update owner. QA/Release must fail a production package if a bundled component has unknown license/provenance.

Treat external projects as bricks behind ports/adapters, not as the architecture. Never replace working Accessible Chess code wholesale merely because an external library exists; adopt only when migration is smaller and safer, and require regression/differential tests.