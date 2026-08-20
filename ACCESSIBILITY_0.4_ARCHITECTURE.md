# Accessible Chess 0.4 — NVDA-first presentation architecture

## Why 0.3.3 was rejected

The first real Windows 11 + NVDA acceptance test showed that the Tkinter/ttk document surface was not practically exposed as a usable screen-reader document. The menu bar was accessible, but the main content did not provide the browse/focus workflow required by the project.

The existing 0.3.x architecture note already warned that Tkinter had not established reliable UI Automation semantics. 0.4 therefore treats 0.3.3 as a chess-functional prototype, not an accessibility baseline.

## 0.4 decision

The Windows presentation layer moves to semantic HTML hosted in Edge/WebView2. The chess core, PGN, engine adapter and storage remain ordinary Python modules.

PGN structure, legality links, and navigation are separate neutral services over
the same canonical `PgnGame`. `acs.gametree_navigation` exposes bounded immutable
paths/cursors and exact RAV return context; it does not flatten or duplicate the
GameTree for accessibility presentation.

`acs.gametree_editing` is the sole copy-on-write structural edit boundary for
promote/reorder/delete. It binds an address to an expected record revision and
returns a complete immutable cursor remap, so stale commands or deleted branch
contexts cannot silently land on a different node.

The proprietary ChessBase boundary remains replaceable and read-only.
`acs.chessbase_cbg_tokens` may prove bounded token/control framing over an exact
SHA-256 payload, but candidate values never bypass the canonical Position,
legality, GameTree, and provenance services. Framing alone keeps both decoder
availability and import safety false.

The UI uses ordinary HTML headings, text, buttons, edit fields, labels, live regions and landmarks so the screen reader consumes a real document instead of a canvas/listbox simulation.

## NVDA interaction contract

Browse mode is the default reading mode. Native NVDA document navigation is intentionally supported:

- H / Shift+H — headings.
- B / Shift+B — buttons.
- E / Shift+E — edit fields.
- F / Shift+F — form fields.
- NVDA+Space — browse/focus mode.
- Escape — leave automatically entered focus mode.

The chess board is not a visual table navigation requirement. A single `Увійти на дошку` button moves focus to a dedicated application/grid interaction surface. Inside it:

- arrows move one logical square;
- Enter/Space selects a source square or plays to the target square;
- Escape leaves board interaction and returns to the document;
- an empty square has accessible name `e 4` only;
- an occupied square has accessible name such as `e 2, білий пішак`.

## Acceptance gate

Automated DOM tests and a successful Windows build are necessary but not sufficient. Version 0.4 may only be marked `NVDA VERIFIED` after a real blind-user NVDA test confirms browse mode, focus mode, headings, buttons, fields, live messages and board interaction.
