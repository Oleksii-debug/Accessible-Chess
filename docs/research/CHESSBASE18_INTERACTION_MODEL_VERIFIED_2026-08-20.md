# ChessBase 18 — verified interaction model notes — 2026-08-20

Scope: competitor UX research for Accessible Chess. This document records current official ChessBase 18 help evidence about interaction architecture. It is not an accessibility endorsement and is not human NVDA evidence.

## 1. Board Window is a pane-based workspace

Official ChessBase 18 help describes the Board Window as the workspace for entering/replaying games, analysis, annotations, position-relevant search and study.

The Board Window contains panes that can be rearranged and individually shown/hidden from View. Important panes include:

- Board — follow or enter moves; board context menu can start a position search.
- Notation — six major display tabs, including full notation, table notation, score sheet, training notation, book and reference.
- Player Photos.
- Extra Book Pane.
- Best Book Lines.
- Reference Search / Reference Database.
- LiveBook.
- Online Database.
- Search Result.
- Engines.
- Plans.

Layouts can be saved and reloaded, including engine/kibitzer configuration. This is strong evidence for a professional chess UX pattern where one chess position is surrounded by replaceable/contextual panes rather than every function opening as an unrelated full-screen page.

Source: https://help.chessbase.com/CBase/18/Eng/board_window.htm

## 2. Notation is synchronized with the board and supports structural variation editing

Official help describes the Notation Window as the display for game notation, variations and commentary.

Interaction model:

- clicking a move in notation jumps the board to that position;
- double-clicking a move opens the text-comment editor;
- the notation context menu exposes functions relevant to game notation;
- variations can be folded/unfolded;
- variations can be promoted or deleted;
- commentary can be inserted;
- diagram-print markers can be added;
- material balance can be displayed;
- notation font is configurable.

Notation tabs include:

- Table notation;
- Training notation;
- Score Sheet;
- Openings Book;
- Reference;
- LiveBook;
- Replay training;
- Surveys;
- MyMoves.

This demonstrates a key UX principle: a game is not just a linear text record. Notation is a synchronized interactive view over the same game/position and can switch into specialized representations without discarding board context.

Source: https://help.chessbase.com/CBase/18/Eng/notation_window.htm

## 3. Alternative-move entry normally creates a variation with minimal interruption

Official Notation Window Toolbar documentation says ChessBase reduces unnecessary variation dialogs:

- when an alternative move is entered, a variation is normally created without displaying the old variation dialog;
- holding Ctrl while entering the alternative move invokes the older dialog/options explicitly;
- a variation dialog is still shown for some ambiguous correction scenarios, especially an alternative to the last move;
- Undo is available through Home -> Undo and Ctrl+Z.

This is useful UX evidence: branch creation should be friction-light in the common case, while ambiguous destructive/correction cases may expose explicit choices.

Source: https://help.chessbase.com/CBase/18/Eng/notation_window_toolbar.htm

## 4. Board-window keyboard model is context-specific

Verified ChessBase 18 board-window bindings include:

- Cursor keys — moves forward/backward through the game.
- Ctrl+G — go to move number.
- T — take back and make the next move a variation.
- Ctrl+Y — delete variation.
- Tab — switch notation.
- M — close variation.
- PageUp/PageDown — scroll notation by page.
- Home/End — beginning/end of notation.
- Ctrl+A — text commentary after move.
- Ctrl+Shift+A — text commentary before move.
- Ctrl+S — save game.
- Ctrl+R — replace game.
- F10 / Ctrl+F10 — next/previous game in list.
- Alt+F2 — start/stop default analysis engine.
- Space — insert best engine move into notation.
- Ctrl+Space — insert best variation from engines into notation.
- Ctrl+Alt+N — open/close notation window.
- Esc — close window.
- Ctrl+Z — undo variation deletion/reordering.

Important interpretation for Accessible Chess: these are Board Window bindings, not evidence that the same chords should become global application actions. Context must remain part of the action/keymap model.

Source: https://help.chessbase.com/CBase/18/Eng/keyboard_board_window.htm

## 5. Engine analysis is a pane attached to current board state

Official help describes an analysis engine/kibitzer as a background process that continuously analyses the current board position.

Interaction model:

- starting an engine opens an engine pane inside the Board Window;
- multiple engines can be present simultaneously;
- default engine can be toggled quickly;
- an engine can be locked to the current position so that subsequent board navigation does not move that engine's analysis target;
- another engine can then analyse a different position.

This proves an important state-model distinction:

`CURRENT_BOARD_POSITION` and `ENGINE_ANALYSIS_TARGET` can normally follow each other, but a deliberate Lock operation decouples them.

Sources:
- https://help.chessbase.com/CBase/18/Eng/engine.htm
- https://help.chessbase.com/CBase/18/Eng/load_engine.htm

## 6. Layout is task-oriented, not fixed

ChessBase/Fritz provide task-oriented layouts. Fritz 18 help documents presets such as:

- Standard;
- Big board;
- Big notation;
- Big engine;
- Big analysis;
- Board only;
- Board and clock;
- Browse book;
- All windows;
- Mini board.

The last layout is restored on next start. A recovery layout can restore important windows if panes are effectively lost.

This suggests a robust desktop principle for Accessible Chess: flexible visual layouts are useful for sighted users, but keyboard/accessibility navigation must be independent of the physical pane arrangement and a deterministic reset-to-known-layout operation is valuable.

Source: https://help.chessbase.com/Fritz/18/Eng/000078.htm

## 7. New board/position/text can be created in the context of a selected database

ChessBase supports Database Window -> File -> New -> Board in... / Position in... / Text in.... The created item belongs to the currently selected database and Ctrl+S stores it there.

This is evidence for preserving database ownership/context when moving from database browsing into editing rather than treating every new board as detached content.

Source: https://help.chessbase.com/CBase/18/Eng/new_in_database.htm

## 8. Interaction principles worth carrying forward for comparison, not automatic adoption

Evidence-backed principles to compare against Scid, Chess Assistant, Lichess, Chess.com and blind-first tools:

1. One canonical position can drive Board + Notation + Engine + Book + Reference + Search-result panes.
2. Notation and board remain synchronized.
3. Common variation creation is low-friction; ambiguous structural edits get explicit choice.
4. Database -> game context can remain meaningful when opening board/edit views.
5. Analysis target can optionally be locked separately from navigation position.
6. Specialized tasks can use different visual layouts without changing the underlying chess state.
7. Keyboard behavior is strongly context-sensitive.
8. A professional interface exposes the same chess content through multiple coordinated representations rather than duplicating chess truth.

These points are candidate interaction principles only. Blind-user usability and NVDA focus/semantics still require separate evidence before adoption.
