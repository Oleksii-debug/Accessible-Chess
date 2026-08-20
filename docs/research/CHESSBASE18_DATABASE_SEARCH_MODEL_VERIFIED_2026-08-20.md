# ChessBase 18 — database/search interaction model — verified 2026-08-20

Research-only notes for Accessible Chess. Sources are current official ChessBase 18 help pages. These findings describe interaction structure; they are not claims of NVDA accessibility.

## Database Window = control center

ChessBase describes Database Window as the main control center/start screen for installing, accessing and managing databases.

Interaction structure:

- Folder tree on the left.
- Selecting a drive/folder shows its databases in the right area.
- A Database Preview pane can show the selected database's game list after a single click.
- Double-clicking a database opens its contents in a full List Window.
- `My databases` is a persistent home/favorites location.
- `Game History` is available from the folder structure.
- Database display can switch between icon/detail styles.

This is an important domain pattern: database selection/management is a workspace in its own right, not merely an Open File dialog.

Source: https://help.chessbase.com/CBase/18/Eng/database_window.htm

## Database-window keyboard model

Official current shortcuts are contextual to Database Window:

- Tab — switch panes.
- Enter — open selected database / start training.
- Ctrl+F — search selected database.
- Ctrl+Alt+L — preview pane toggle.
- Ctrl+O — open database and add to My databases.
- Ctrl+X — create database.
- Ctrl+L — games list.
- Ctrl+P — player index.
- Ctrl+T — tournament index.
- Ctrl+A — annotator index.
- Ctrl+S — source index.
- Ctrl+K — openings key.
- Ctrl+C / Ctrl+V — database game-copy workflow in this window context.

This is direct evidence that the same physical chord may have domain-specific meaning in a non-editable database-management context while standard text editing semantics must still be preserved inside editable controls.

Source: https://help.chessbase.com/CBase/18/Eng/keyboard_db.htm

## Games List is a reusable result/browser surface

ChessBase says Games List is the most frequently used window type and reuses it for:

- browsing a database;
- search results;
- contents of an openings key;
- games of a player;
- related list-oriented database views.

Interaction model:

- configurable/resizable/reorderable columns;
- configuration persists;
- sort via column headers;
- column visibility through header context menu;
- multi-selection through Ctrl-click or Shift+cursor;
- Ctrl+A selects all list elements;
- Ribbon actions include Filter List, Copy, Edit, Clip and Delete;
- context menu is a major command surface for selected games.

This suggests a useful design principle for Accessible Chess: use one stable semantic `GameList` interaction model across Library, Search Results, Player Results, Import Result and similar contexts, rather than inventing separate incompatible lists for each feature.

Source: https://help.chessbase.com/CBase/18/Eng/games_list.htm

## Search Mask is a composable filter workflow

ChessBase distinguishes search invoked from:

1. a Games List; and
2. one or more databases from Database Window.

Both are initiated through the same search concept (`Ctrl+F`). The current workflow begins with an interactive search mask; `Advanced` exposes the full multi-tab mask.

Advanced categories include:

- Game data — players/tournaments/years/results etc.;
- Annotations;
- Position;
- Material;
- Manoeuvres;
- Medals;
- Attacks.

Additional behaviors:

- criteria can be combined;
- search may optionally include variation lines, not only main line;
- Reset clears all search sections;
- searches can be saved as reusable `.dbsearch` presets and loaded later;
- the same search model can be entered from Database Window, List Window or Board Window position context.

This is important architecture evidence: Search is not a separate disconnected feature. It is a reusable query model callable from different contexts with results returning through the shared game-list surface.

Source: https://help.chessbase.com/CBase/18/Eng/000134.htm

## Interactive Search Mask provides immediate expected-result feedback

Current ChessBase help describes its newer Interactive Search Mask as easier to use than the classic advanced mask and able to show information about expected game counts before executing the full search.

Common criteria include:

- player;
- tournament;
- ECO;
- material;
- position.

`Advanced` remains available for the full search system.

This is a useful pattern to evaluate for Accessible Chess: progressive disclosure can keep common searches simple without deleting professional search power.

Source: https://help.chessbase.com/CBase/18/Eng/interactive_search_mask.htm

## Position search is board-integrated

ChessBase allows position search to originate from the chess board. A position/motif builder can be used as a query, and matching games are listed while the board shows the first matching occurrence. The input board can then refine the query by moving/removing pieces.

This is a major UX pattern: board state can be a first-class database query, rather than requiring the user to manually translate every positional idea into text fields.

Sources:
- https://help.chessbase.com/CBase/18/Eng/interactive_search_mask_any_po.htm
- https://help.chessbase.com/CBase/18/Eng/board_window.htm

## Indexes are alternate database navigation models

ChessBase exposes database indexes such as:

- Player;
- Tournament;
- Annotator;
- Source;
- Team;
- Openings;
- General themes;
- Tactics;
- Strategy;
- Endgame;
- Final material.

Player Index itself is searchable and can branch into White/Black games, ID card/dossier, player statistics and metadata editing.

This indicates that professional database exploration is not only a global search box. Users also navigate stable semantic indexes/entities.

Sources:
- https://help.chessbase.com/CBase/18/Eng/games_indexes.htm
- https://help.chessbase.com/CBase/18/Eng/player_index.htm

## Opening Book and Reference are distinct from engine analysis

ChessBase's Opening Book is entered from the Notation -> Book tab and represents position-based move statistics/tree data. It can be built from databases or generated on the fly from selected games.

Book Analysis / Best Book Line shows full statistical variations. A selected line can:

- jump to its end position;
- be copied into current notation;
- be explored on a small Variation Board;
- be filtered by frequency.

Opening Reference uses the current board position to derive database statistics/reference information and can be shown as a notation tab or separate pane.

This proves a core UX distinction Accessible Chess should preserve:

- Engine Analysis = calculated evaluations/PVs;
- Opening Book = position/move tree/statistics;
- Opening Reference = database evidence from matching games.

Sources:
- https://help.chessbase.com/CBase/18/Eng/openings_book.htm
- https://help.chessbase.com/CBase/18/Eng/book_analysis_window.htm
- https://help.chessbase.com/CBase/18/Eng/referenceondbase.htm

## Candidate interaction principles to compare with other products

1. Stable Database Window as library/control center.
2. Stable reusable Game List as the result surface for many database journeys.
3. Progressive search: simple interactive mask -> advanced professional mask.
4. Search can originate from Library/List/Board while using one underlying query concept.
5. Database indexes provide semantic browsing beside free-form search.
6. Board position is a valid search query source.
7. Search/result/library should preserve enough context to return to the originating selection.
8. Book, Reference and Engine are separate concepts even though all are position-driven.
9. Professional power can live behind panes/tabs/progressive disclosure rather than forcing every control into the primary screen.

These are evidence-backed competitor patterns for later cross-product synthesis, not automatic Accessible Chess requirements.
