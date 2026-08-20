# Accessible Chess competitor interaction lab — bootstrap findings — 2026-08-20

Research-only evidence. This branch is isolated from Stage 1 release/QA. Nothing here is human NVDA verification.

## Evidence labels

- DOC_CONFIRMED — current official documentation/page inspected.
- WEB_SEMANTIC_OBSERVED — current public page surface observed through web retrieval.
- ROBOT_PENDING — GitHub Playwright/UIA job prepared or running; result not yet accepted.
- BLOCKED_UNSAFE_INSTALL — automatic execution is intentionally prohibited because the available official path requests/encourages weakening Windows security or has unresolved malware history.
- PRACTICAL_INTERACTIVE_WINDOWS_REQUIRED — hosted CI cannot prove the unlocked-desktop/screen-reader behavior.

## Lichess

Status: DOC_CONFIRMED + WEB_SEMANTIC_OBSERVED + ROBOT_PENDING.

Current analysis page exposes an accessibility control at the start of the page: `Accessibility - Enable blind mode`.

Current official Blind Mode tutorial (last update stated 2026-05-13) documents a distinct nonvisual interaction model rather than merely adding shortcuts to the normal visual board. Important patterns:

- Browse Mode for reading/navigation and Focus Mode for form/board interaction.
- Blind Mode simplifies/linearizes the page and exposes screen-reader-oriented interaction.
- Board and typed-command interaction coexist.
- `i` jumps from focused board to command input.
- `o` announces current square/piece, `l` last move, `c` captured piece, `t` clocks, `m` legal moves for selected piece.
- Board Actions ordering can be changed relative to the board.
- Current blind-mode board is also visually rendered for sighted/low-vision testers, demonstrating a useful principle: the accessible representation need not be a separate invisible product.

Current public analysis page also exposes Tools routes such as Analysis board, Openings, Board editor, Import game and Advanced search.

Sources inspected:
- https://lichess.org/analysis
- https://lichess.org/page/blind-mode-tutorial
- https://lichess.org/page/blind-mode-changelog

Practical robot prepared:
- normal analysis/editor/import/study surface capture;
- keyboard Tab sequence;
- ARIA snapshot where supported;
- real activation of `Accessibility: Enable blind mode`;
- second surface/focus capture after Blind Mode activation.

## Chess.com

Status: DOC_CONFIRMED + WEB_SEMANTIC_OBSERVED + ROBOT_PENDING.

Current official Analysis help (2026-01-27) describes a mainstream visual workflow:

- Analysis is entered from the left-side Train menu.
- One analysis workspace supports free moves, Setup Position, collections/history/study import and FEN/PGN loading.
- Setup Position uses a board/piece palette plus side-to-move, castling-right controls, reset/empty-board actions and FEN/PGN text boxes followed by Load.
- Game Details is opened from an Edit/pencil control and holds metadata such as player names/ratings/result/event/time control/location/round/ECO/date.
- Engine/interface/board settings live behind the analysis Settings control.
- Practice vs Computer can branch from the selected analysis position.

Current Game Review differs from Self Analysis: Game Review is guided/coached; Self Analysis is free exploration with engine lines/arrows. Arrow keys can navigate reviewed moves and coach feedback follows the selected move.

Accessibility status is evolving: Chess.com announced improved screen-reader support for core pages in May 2026, but it explicitly states accessibility work is still ongoing. Robot evidence must therefore be feature-specific rather than treating the whole site as screen-reader-complete.

Sources inspected:
- https://www.chess.com/analysis
- https://support.chess.com/en/articles/8583825-how-do-i-use-the-analysis-board
- https://support.chess.com/en/articles/8584089-how-does-game-review-work
- https://www.chess.com/blog/chesscom/screen-reader-now-compatible-with-core-chess-com-pages

## SK Chess

Status: DOC_CONFIRMED; automatic installer execution intentionally not accepted yet.

Official SK Chess v1.4 page describes five keyboard-navigable areas:

1. Select Game.
2. Game Area.
3. Annotation.
4. text Board using IBCA phonetic alphabet.
5. Engine Suggestions.

Documented interaction:
- Left/Right moves through game.
- Up/Down moves within a variation dialog and engine suggestions.
- Space accepts/explores an engine suggestion.
- comments produce an auditory notification.
- explicit speak-position / speak-annotation / speak-last-move actions.

The same official site warns that antivirus may need to be disabled and tells users to use Windows Defender `Run Anyway` if blocked. Accessible Chess research automation MUST NOT disable Defender/SmartScreen or automatically choose Run Anyway. Until the binary can be independently acquired/verified through a safe path, automated execution is classified BLOCKED_UNSAFE_INSTALL, while docs/video research remains allowed.

Sources inspected:
- https://accessiblechess.in/
- https://accessiblechess.in/skchess

## ChessBase Reader 2017

Status: DOC_CONFIRMED + ROBOT_PENDING.

ChessBase's current support/download page still offers Reader 2017 as a free Windows download and states it opens `.cbh`, `.cbf` and `.pgn`, plays through games and can display ChessBase training material.

A ChessBase support article provides the official direct MSI:
`https://download.chessbase.com/download/chessbasereader/Reader2017Setup_x86.msi`

GitHub Windows robot prepared to:
- download only from that ChessBase domain;
- capture SHA-256;
- inspect Authenticode status/signer;
- install silently without bypassing Windows security;
- locate the actual Reader executable;
- launch a small synthetic PGN with a variation and comments;
- enumerate UI Automation controls;
- attempt focus + Tab / Alt+F / Escape / arrows;
- record whether GitHub-hosted Windows provides a usable interactive desktop.

Sources inspected:
- https://support.chessbase.com/en/downloads
- https://en.chessbase.com/support-kb/content/details/871/Format_change_in_ChessBase_Magazine

## Scid 5.2

Status: DOC_CONFIRMED + ROBOT_PENDING.

Current SourceForge Scid project lists Scid 5.2 Windows x64 as the latest line, with a ZIP build. The ZIP route is preferred for the CI probe because it avoids installer UI and is appropriate for an ephemeral test runner.

GitHub Windows robot prepared to:
- download the current Windows x64 ZIP from the project distribution;
- hash and extract it;
- locate the Scid executable;
- launch a synthetic PGN;
- enumerate UI Automation controls;
- attempt focus / Tab / Alt+F / Escape / arrows / Home / End.

Source inspected:
- https://sourceforge.net/projects/scid/files/Scid/

## Arena 3.5.1

Status: PRACTICAL TEST DESIRABLE, but automatic download/launch is deferred pending a trustworthy current binary path.

Arena remains relevant for engine/analysis GUI conventions, but historic discussions around the old official download site include reports of malware/injected JavaScript and antivirus warnings. We do not use random mirrors or weaken security merely to obtain a practical test.

Research next action: identify a current trustworthy package hash/source or build reproducibly from trusted source before execution.

## WinBoard

Status: DOC_CONFIRMED; safe current Windows binary source still needs resolution before CI execution.

GNU confirms WinBoard is the Windows port of XBoard and supports PGN plus local engines. Current GNU project pages are useful primary documentation, but the Windows binary distribution history is old/fragmented. Do not substitute untrusted abandonware/Houdini bundles for a canonical test target.

Source inspected:
- https://www.gnu.org/software/xboard/

## Current practical-lab branch

`research/competitor-interaction-lab-20260820`

The branch contains reusable Playwright and Windows UIA probes plus an isolated GitHub Actions workflow. Evidence generated by robots must remain distinct from Oleksii's human Windows/NVDA acceptance.
