# Accessible Chess — competitor-derived interaction contracts

Status: normative UX contract for the Windows product, derived from durable
competitor evidence at `0213f54f3f36fb30379f95c9979aea3a1cc41481`.

This document defines interaction behavior, not visual cloning. Accessible
Chess remains Windows-only and accessibility-first. One canonical Position,
GameTree, Library, engine, book and teaching state drives both the visual and
NVDA projections. A robot/UIA observation is never human NVDA verification.

## Evidence boundary

- ChessBase 18: current official help establishes the professional pane,
  notation, engine, database, search, opening-reference and opening-book
  interaction model. It does not establish accessibility.
- ChessBase Reader 2017: a signed official MSI installed and launched on a
  GitHub Windows runner. Keyboard/UIA evidence is practical, but most controls
  appeared as unnamed, non-focusable panes. Domain patterns may be adopted;
  its accessibility defects must not be copied.
- Lichess: current public semantic surfaces and official Blind Mode
  documentation exist. The robot found the Blind Mode button, but activation
  timed out because the control remained outside the viewport. Activated Blind
  Mode behavior is therefore documentation-confirmed, not practically proven
  by this run.
- Chess.com: current Analysis and Lessons semantic surfaces plus official help
  establish mainstream workflows. Chess.com states accessibility work is
  ongoing, so evidence is feature-specific.
- SK Chess: current documentation establishes a blind-first five-area model,
  explicit speak commands, typed moves and variation navigation. The binary
  was not executed because the documented route recommends weakening Windows
  security.
- Scid 5.2 and ChessX 1.6.10: practical execution is insufficient evidence.
  The selected SourceForge downloads were HTML/error payloads, not the expected
  ZIP/installer.

Allowed decisions are `ADOPT_AS_DEFAULT`, `ADOPT_CONTEXTUALLY`,
`COMPAT_PROFILE_ONLY`, `INSPIRE_BUT_IMPROVE`,
`REJECT_ACCESSIBILITY_DEFECT`, and `INSUFFICIENT_EVIDENCE`.

## Cross-cutting invariants

1. Keyboard and visual input converge on the same canonical application
   actions and state.
2. Editable controls retain Windows editing semantics. Product shortcuts must
   not steal `Ctrl+A`, `Ctrl+C`, `Ctrl+X`, `Ctrl+V` or `Ctrl+Z` from them.
3. Menu paths are the authoritative discoverability surface; shortcuts are
   optional accelerators registered against the same action IDs.
4. Escape closes the innermost transient surface first. Return restores the
   exact originating selection, node, paragraph, filter, sort and scroll state.
5. Visual pane arrangement never determines NVDA reading order. A deterministic
   reset-to-default layout remains available.
6. Move, Position Editor, Annotation, Teacher Pointer, Student Hover and
   Student Selection remain separate command families.
7. Error messages are concise, actionable and focus-safe; no exception dumps
   or developer prose enter user UI.

## 1. Playing

- **USER_INTENT:** Start or continue a legal chess game and enter moves without
  losing position, clock, notation or focus context.
- **ENTRY_POINT:** `Game > New Game`, recent game, opened PGN/database game, or
  the always-available Move Input in an active game.
- **WINDOW/PANE/DIALOG:** Board workspace with Board, Move Input, Notation,
  Clocks/Game Status and optional captured-material panes; settings use a
  bounded New Game dialog.
- **FOCUS_ENTRY:** New Game enters its first required setting; confirming places
  focus in Move Input. Reopening an active game restores the last logical board
  or notation location.
- **STATE:** Canonical game position, side to move, clocks, result, history
  node, orientation and user settings.
- **ACTIONS:** Enter SAN/UCI-compatible move text; navigate board and history;
  undo/takeback where policy allows; offer draw, resign, stop, save and review.
- **ESCAPE/RETURN:** Escape cancels an unopened move/dialog without changing
  chess state. Leaving and returning restores the same game node and focus
  family.
- **FOCUS_RESTORATION:** Successful move clears Move Input and keeps focus
  there. Illegal input remains selected/preserved with a short error.
- **VISUAL_PROJECTION:** Standard board, clocks, last-move highlight, notation
  and game status.
- **ACCESSIBLE_PROJECTION:** Concise Move Input; side to move; last move; clocks;
  status; linear notation; 64-square Board Explorer; explicit speak/query
  actions.
- **CANONICAL_ACTION:** `game.new`, `move.submit`, `game.undo`, `game.redo`,
  `game.resign`, `game.stop`, `history.previous`, `history.next`.
- **MENU_PATH:** `Game`, `Move`, `Navigate`, `Speak`.
- **SHORTCUT_POLICY:** Arrow navigation is contextual. Typing in Move Input is
  never treated as a board shortcut. Standard edit chords win in editable
  controls.
- **ERROR_RECOVERY:** Illegal/ambiguous move does not mutate state; engine or
  clock failure pauses safely and offers retry/continue/save.
- **COMPETITOR_EVIDENCE:** Lichess Blind Mode documents coexisting typed and
  board interaction plus last-move/clock/legal-move queries. SK Chess documents
  typed moves, Left/Right history and explicit speak actions.
- **DECISION:** `ADOPT_AS_DEFAULT`.

## 2. Engine Play

- **USER_INTENT:** Play a complete game against Stockfish with explicit side,
  strength and time settings.
- **ENTRY_POINT:** `Game > Play Against Engine` or `Engine > New Engine Game`.
- **WINDOW/PANE/DIALOG:** New Engine Game dialog followed by the normal Board
  workspace; engine lifecycle status is not mixed with analysis PV controls.
- **FOCUS_ENTRY:** First required game setting, then Move Input when the human
  is to move or a concise waiting/status control when the engine moves first.
- **STATE:** Canonical game plus engine provider/session, human side, limits,
  clock policy, pending request identity and terminal result.
- **ACTIONS:** Start, human move, engine reply, pause/stop, takeback if allowed,
  resign, restart and save.
- **ESCAPE/RETURN:** Escape cancels setup before provider creation. Stop closes
  the owned engine process; returning to the game does not spawn a duplicate.
- **FOCUS_RESTORATION:** After the engine reply, focus returns to the prior
  Move Input/board query context and announces the move once.
- **VISUAL_PROJECTION:** Board, clocks, engine identity/strength and last move;
  no analysis advantage leak unless explicitly enabled.
- **ACCESSIBLE_PROJECTION:** Short engine-thinking state, engine move, clock and
  game status; no continuous PV chatter.
- **CANONICAL_ACTION:** `engine_play.configure`, `engine_play.start`,
  `engine_play.stop`, `move.submit`, `game.takeback`.
- **MENU_PATH:** `Game > Play Against Engine`; lifecycle actions also under
  `Engine`.
- **SHORTCUT_POLICY:** No competitor-specific global chord is adopted by
  default; every accelerator is remappable and inactive inside text editing.
- **ERROR_RECOVERY:** Missing/crashed/hung provider fails closed, cancels stale
  requests, preserves the game and exposes Retry or Choose Engine. Shutdown is
  idempotent and cannot orphan a process silently.
- **COMPETITOR_EVIDENCE:** Chess.com documents Practice vs Computer from a
  selected analysis position. ChessBase distinguishes background engine panes;
  SK Chess documents loading Stockfish. None proves Accessible Chess lifecycle
  safety.
- **DECISION:** `INSPIRE_BUT_IMPROVE`.

## 3. Engine Analysis

- **USER_INTENT:** Analyse the current canonical position continuously, inspect
  multiple PVs, explore one temporarily and insert it only on request.
- **ENTRY_POINT:** `Engine > Start Analysis`, context action from Board,
  Notation, Database result, Book position or Training review.
- **WINDOW/PANE/DIALOG:** Analysis pane attached to the current workspace; engine
  choice/settings use a bounded dialog.
- **FOCUS_ENTRY:** Starting analysis does not steal focus. Explicitly opening
  the pane focuses its summary or first PV.
- **STATE:** Analysis session, request generation, target position/node,
  follow/locked mode, MultiPV results and selected PV.
- **ACTIONS:** Start/stop/restart; choose engine; set limits/MultiPV; next/previous
  PV; explore; return; lock/unlock target; insert selected move/line explicitly.
- **ESCAPE/RETURN:** Escape exits temporary PV exploration to the exact source
  node. Stopping analysis returns focus without altering GameTree.
- **FOCUS_RESTORATION:** Database/book/notation origin and selected PV are
  restored after temporary exploration.
- **VISUAL_PROJECTION:** Evaluation, mate score, depth, nodes/time/speed and
  structured PV rows, optionally arrows.
- **ACCESSIBLE_PROJECTION:** Stable summary plus navigable PV rows; updates are
  throttled and user-controlled rather than live-region spam.
- **CANONICAL_ACTION:** `analysis.start`, `analysis.stop`, `analysis.lock_target`,
  `analysis.explore_pv`, `analysis.return`, `analysis.insert_move`,
  `analysis.insert_line`.
- **MENU_PATH:** `Engine > Analysis`; context menu may invoke the same actions.
- **SHORTCUT_POLICY:** ChessBase `Alt+F2`, Space and `Ctrl+Space` are optional
  compatibility-profile candidates only; Space must never insert a line while
  focus is in a button, list or editor unexpectedly.
- **ERROR_RECOVERY:** Results carry request/position identity; stale results are
  rejected. Crash/timeout preserves the position and offers restart without a
  process leak.
- **COMPETITOR_EVIDENCE:** ChessBase 18 documents engine panes, multiple engines,
  target locking and explicit best-move/variation insertion. Lichess exposes
  separate engine settings and opening-explorer controls.
- **DECISION:** `ADOPT_CONTEXTUALLY`.

## 4. PGN / GameTree

- **USER_INTENT:** Read, create and structurally edit a complete game with
  comments, NAGs and nested variations while always knowing the current node.
- **ENTRY_POINT:** Open/import PGN, New Game, Database game, Book embedded game
  or current game notation.
- **WINDOW/PANE/DIALOG:** Synchronized Board and structured Notation panes;
  comment editing and ambiguous branch replacement use bounded dialogs.
- **FOCUS_ENTRY:** Open at mainline start, saved node, search occurrence or
  explicitly selected node; focus enters the Notation tree without changing it.
- **STATE:** One canonical bounded GameTree, current node, sibling/parent path,
  folded visual state, selection and source provenance.
- **ACTIONS:** Previous/next node; enter/leave variation; next sibling; add
  alternative; promote/reorder/delete variation; edit before/after comment;
  NAG; save/export; undo/redo structural operation.
- **ESCAPE/RETURN:** Escape closes comment/choice dialogs or exits temporary
  exploration. Return from a branch restores the exact parent and outgoing
  edge, never a guessed mainline node.
- **FOCUS_RESTORATION:** Structural edits retain the nearest surviving node and
  announce the new relationship. Cancel restores the original node and text.
- **VISUAL_PROJECTION:** Traditional rich notation with folded variations,
  comments, symbols and synchronized board.
- **ACCESSIBLE_PROJECTION:** Tree/list semantics over the same GameTree, with
  node move, variation depth, sibling count, comment/NAG presence and explicit
  parent/return actions.
- **CANONICAL_ACTION:** `gametree.previous`, `gametree.next`,
  `gametree.enter_variation`, `gametree.next_sibling`, `gametree.parent`,
  `gametree.promote`, `gametree.delete`, `comment.before`, `comment.after`.
- **MENU_PATH:** `Navigate`, `Variation`, `Annotate`, `File > Save/Export`.
- **SHORTCUT_POLICY:** Common alternative entry is low-friction; ambiguous
  destructive correction asks explicitly. ChessBase branch chords are offered
  only through a compatibility profile after conflict checks.
- **ERROR_RECOVERY:** Parser and serializer enforce byte/node/depth bounds,
  reject cycles/reused nodes, preserve damaged source evidence and save
  atomically with expected-source protection.
- **COMPETITOR_EVIDENCE:** ChessBase 18 documents synchronized notation,
  fold/promote/delete/comment actions and low-friction variation creation. SK
  Chess documents Left/Right main navigation and Up/Down variation choices.
- **DECISION:** `ADOPT_AS_DEFAULT`.

## 5. Multi-game PGN

- **USER_INTENT:** Open, search, traverse and save a PGN containing many games
  without flattening it into one game or losing file context.
- **ENTRY_POINT:** `File > Open PGN`, drag/drop or import.
- **WINDOW/PANE/DIALOG:** Reusable Game List plus Board/Notation workspace for
  the selected game.
- **FOCUS_ENTRY:** Game List first, with file name and game count; opening a row
  enters the game at its saved/start node.
- **STATE:** Source identity/SHA, ordered game collection, selected row, sort,
  filter, scroll, per-game GameTree and dirty state.
- **ACTIONS:** Next/previous game; open; filter; multi-select; copy/export
  selection; save one or all; return to list.
- **ESCAPE/RETURN:** Escape from a game returns to the same list row/filter/sort;
  closing a dirty collection requests one explicit save decision.
- **FOCUS_RESTORATION:** Exact row and selection set are restored after viewing
  or editing a game.
- **VISUAL_PROJECTION:** Configurable sortable game table and synchronized
  preview/workspace.
- **ACCESSIBLE_PROJECTION:** Semantic table/list with stable columns, row count,
  selected-game summary and deterministic next/previous commands.
- **CANONICAL_ACTION:** `pgn.open_collection`, `game_list.open`,
  `game_list.next`, `game_list.previous`, `game_list.return`,
  `pgn.save_collection`.
- **MENU_PATH:** `File > Open/Save/Export`; `Navigate > Next/Previous Game`.
- **SHORTCUT_POLICY:** `F10`/`Ctrl+F10` may be a compatibility profile, not an
  undocumented global default. Standard list selection chords are preserved.
- **ERROR_RECOVERY:** One malformed game is isolated with an ImportReport; the
  remaining collection stays navigable. Save is atomic and never silently
  drops unsupported tokens.
- **COMPETITOR_EVIDENCE:** ChessBase reuses Games List for database/result
  contexts and documents next/previous-game shortcuts. SK Chess starts with a
  Select Game area for opened PGN files. Lichess Import exposes PGN import but
  does not prove local multi-game round-trip behavior.
- **DECISION:** `ADOPT_AS_DEFAULT`.

## 6. Database

- **USER_INTENT:** Manage chess libraries, browse stable semantic indexes and
  open a game without losing library context.
- **ENTRY_POINT:** `Database > Library`, recent database or import completion.
- **WINDOW/PANE/DIALOG:** Database/Library workspace with source tree/list,
  reusable Game List and optional preview.
- **FOCUS_ENTRY:** Last selected library/source, otherwise the Library tree;
  opening a database focuses its Game List.
- **STATE:** ACSDB schema/version, selected source/database, Game List query,
  row, sort/filter/scroll, indexes and provenance.
- **ACTIONS:** Create/open/import; browse games, players, events, sources and ECO;
  preview/open; export; inspect import history; backup/recover.
- **ESCAPE/RETURN:** Escape leaves a preview or game and returns to the exact
  database/list selection. It never closes the database unexpectedly.
- **FOCUS_RESTORATION:** `DATABASE -> ROW -> GAME -> RETURN` restores the same
  row, filter, sort and scroll.
- **VISUAL_PROJECTION:** Library navigation plus configurable Game List columns
  and preview panes.
- **ACCESSIBLE_PROJECTION:** Named regions, semantic tree/table, stable column
  announcements, row position/count and explicit context breadcrumb.
- **CANONICAL_ACTION:** `database.open`, `database.import`, `library.select`,
  `game_list.open`, `game_list.return`, `database.backup`.
- **MENU_PATH:** `Database`; selected-row actions in `Game` and context menu.
- **SHORTCUT_POLICY:** Database-context shortcuts may exist, but editable text
  retains Windows semantics. Tab order is logical and independent of visual
  pane arrangement.
- **ERROR_RECOVERY:** Versioned migration backs up first, writes atomically,
  rolls back on injected failure and reports corruption/unsupported versions
  without mutating the source.
- **COMPETITOR_EVIDENCE:** ChessBase 18 documents Database Window as a control
  center, persistent My Databases, preview, semantic indexes and a reusable
  Games List. Reader 2017 robot confirmed real folder/game list panes but also
  exposed weak/unnamed UIA semantics.
- **DECISION:** `INSPIRE_BUT_IMPROVE`.

## 7. Search

- **USER_INTENT:** Find games by literal metadata, position, material or other
  supported criteria and return to the same origin after inspection.
- **ENTRY_POINT:** `Database > Search`, `Ctrl+F` in non-editable Library/Game
  List context, or `Search This Position` from Board.
- **WINDOW/PANE/DIALOG:** Simple search dialog with Advanced disclosure;
  results use the shared Game List.
- **FOCUS_ENTRY:** First common criterion or the current-board position summary
  when entered from Board.
- **STATE:** Versioned query model, origin context, criteria, include-variations
  policy, result order and selected row.
- **ACTIONS:** Add/remove/reset criteria; literal metadata search; position and
  material search; include variations; save/load preset; execute/cancel;
  open result and return.
- **ESCAPE/RETURN:** Escape cancels without destroying the prior query/results.
  Return from an opened game restores the exact result row and origin.
- **FOCUS_RESTORATION:** Validation returns to the offending criterion; success
  focuses result count then first row.
- **VISUAL_PROJECTION:** Progressive simple/advanced criteria and sortable Game
  List; board query editor where appropriate.
- **ACCESSIBLE_PROJECTION:** Labelled criteria groups, concise expected/result
  count, semantic results table and explicit active-filter summary.
- **CANONICAL_ACTION:** `search.open`, `search.reset`, `search.execute`,
  `search.cancel`, `search.save_preset`, `search.open_result`,
  `search.return_to_results`.
- **MENU_PATH:** `Database > Search`; `Board > Search This Position`.
- **SHORTCUT_POLICY:** `Ctrl+F` is contextual outside editors; inside editable
  content it retains native Find behavior. `%`, `_` and `!` are literal user
  text unless an explicit query operator is selected.
- **ERROR_RECOVERY:** Query validation is fail-closed; long searches expose
  progress/cancel; cancellation leaves the database and prior results intact.
- **COMPETITOR_EVIDENCE:** ChessBase 18 documents a shared composable search
  mask, simple-to-advanced disclosure, saved presets, variation search,
  position-origin queries and reusable Game List results.
- **DECISION:** `ADOPT_AS_DEFAULT`.

## 8. Opening Reference

- **USER_INTENT:** Inspect database evidence for the current position: matching
  games, move frequencies and contextual metadata.
- **ENTRY_POINT:** `Position > Opening Reference` or dedicated tab/pane from a
  Board/Notation position.
- **WINDOW/PANE/DIALOG:** Reference pane attached to the current workspace with
  shared Game List for underlying games.
- **FOCUS_ENTRY:** Opening does not steal focus; explicit pane navigation enters
  its summary or first candidate move.
- **STATE:** Canonical position key, database/query identity, statistics,
  selected move/result and source node.
- **ACTIONS:** Refresh; choose candidate move; open matching games; filter;
  explore and return to source position.
- **ESCAPE/RETURN:** Escape leaves reference exploration and restores the exact
  originating node; closing the pane does not change the position.
- **FOCUS_RESTORATION:** Selected reference row is retained across game review.
- **VISUAL_PROJECTION:** Statistical candidate-move table and matching-game
  results synchronized with the board.
- **ACCESSIBLE_PROJECTION:** Candidate move, count/score/percentage and source
  database announced as structured rows, not a visual chart alone.
- **CANONICAL_ACTION:** `reference.open`, `reference.refresh`,
  `reference.select_move`, `reference.open_games`, `reference.return`.
- **MENU_PATH:** `Position > Opening Reference`; optional View pane toggle.
- **SHORTCUT_POLICY:** No unverified competitor chord is adopted; live keymap
  and menus provide discovery.
- **ERROR_RECOVERY:** Missing/stale database reports unavailable evidence and
  preserves the board. Partial results carry provenance and cancellation state.
- **COMPETITOR_EVIDENCE:** ChessBase 18 documents Opening Reference as
  position-driven database statistics in a notation tab or separate pane.
  Lichess robot observed a distinct Opening explorer/tablebase control.
- **DECISION:** `ADOPT_AS_DEFAULT`.

## 9. Opening Book

- **USER_INTENT:** Explore a position-based move tree with weights/statistics
  and optionally copy a chosen line into the current GameTree.
- **ENTRY_POINT:** `Position > Opening Book`, Notation Book tab, or configured
  book for engine play.
- **WINDOW/PANE/DIALOG:** Opening Book pane plus optional bounded Variation
  Board; it is distinct from Engine Analysis and Opening Reference.
- **FOCUS_ENTRY:** Book summary/first candidate move while preserving source
  board focus for quick return.
- **STATE:** Book identity/version, canonical position key, candidate moves,
  weights/statistics, selected line and source node.
- **ACTIONS:** Next/previous candidate; explore line; jump to line end; return;
  filter; explicitly insert move/line; choose book for engine play.
- **ESCAPE/RETURN:** Escape exits line exploration to the exact source node;
  closing Book never writes to GameTree.
- **FOCUS_RESTORATION:** Selected book row and source position survive temporary
  exploration.
- **VISUAL_PROJECTION:** Candidate table/tree, statistics and Variation Board.
- **ACCESSIBLE_PROJECTION:** Structured candidate rows and line steps with
  explicit Explore, Return and Insert actions.
- **CANONICAL_ACTION:** `book.open`, `book.select_move`, `book.explore_line`,
  `book.return`, `book.insert_move`, `book.insert_line`.
- **MENU_PATH:** `Position > Opening Book`; `Engine > Opening Book Settings`.
- **SHORTCUT_POLICY:** Space does not silently insert a move by default; any
  compatibility mapping is context-bound and user-visible.
- **ERROR_RECOVERY:** Invalid/corrupt book is read-only, reports capability and
  leaves the canonical position/GameTree unchanged.
- **COMPETITOR_EVIDENCE:** ChessBase 18 explicitly separates Opening Book,
  Book Analysis/Best Book Line, Opening Reference and Engine Analysis.
- **DECISION:** `ADOPT_AS_DEFAULT`.

## 10. Position Setup / FEN

- **USER_INTENT:** Construct or load an exact legal chess position using only
  the keyboard, validate it, and commit or cancel atomically.
- **ENTRY_POINT:** `Position > Set Up Position`, `File > New Position`, pasted
  FEN or contextual Edit Position.
- **WINDOW/PANE/DIALOG:** Dedicated Position Editor dialog/workspace, never Move
  Input; includes board editor and explicit state fields.
- **FOCUS_ENTRY:** First editor action or current-square summary; existing
  position is copied into isolated draft state.
- **STATE:** Draft board, side to move, castling rights, en-passant square,
  halfmove/fullmove counters, validation errors and original snapshot.
- **ACTIONS:** Place/remove piece; clear/start position; move editor cursor;
  set side/castling/en-passant/counters; paste/copy FEN; validate; OK/Cancel.
- **ESCAPE/RETURN:** Escape/Cancel discards the complete draft. OK commits one
  validated PositionEditor command and returns to the origin.
- **FOCUS_RESTORATION:** Validation focuses the exact invalid field/square;
  cancel restores origin focus and unchanged position.
- **VISUAL_PROJECTION:** Board/piece palette and state controls with orientation
  and legal-status summary.
- **ACCESSIBLE_PROJECTION:** Keyboard square editor, piece/state commands,
  concise position summary, labelled state fields and complete error list.
- **CANONICAL_ACTION:** `position_editor.open`, `position_editor.place_piece`,
  `position_editor.remove_piece`, `position_editor.set_state`,
  `position_editor.validate`, `position_editor.commit`,
  `position_editor.cancel`.
- **MENU_PATH:** `Position > Set Up Position`; FEN actions under `Edit` or
  `Position` without stealing clipboard chords from text fields.
- **SHORTCUT_POLICY:** Coordinate text in this workspace is editor input, never
  MoveCommand or TeacherPointerCommand. Standard editing semantics apply.
- **ERROR_RECOVERY:** Draft is isolated and bounded. Invalid kings, side,
  castling/en-passant/counters or malformed FEN cannot partially mutate the
  canonical position.
- **COMPETITOR_EVIDENCE:** Chess.com documents Setup Position with board/palette,
  side/castling controls, reset/empty and FEN/PGN Load. Lichess robot observed
  Starting Position, Clear Board, side-to-play, variant, copy, analysis and
  play-from-here actions.
- **DECISION:** `INSPIRE_BUT_IMPROVE`.

## 11. Instructional Books

- **USER_INTENT:** Read a semantic chess book linearly, open embedded chess
  content for exploration/analysis, and return to the exact paragraph.
- **ENTRY_POINT:** `Library > Books`, recent book, chapter link or search result.
- **WINDOW/PANE/DIALOG:** Book reader with TOC, semantic reading pane and shared
  Board/Notation/Engine workspace for embedded content.
- **FOCUS_ENTRY:** Saved chapter/block/paragraph, otherwise book title and TOC.
- **STATE:** Immutable BookDocument/version, current semantic block, reading
  offset, embedded position/game identity and isolated navigation snapshot.
- **ACTIONS:** TOC/chapter/previous/next block; read heading/paragraph/note;
  open diagram/position/game/variation/exercise; analyse; return; bookmark.
- **ESCAPE/RETURN:** Escape closes embedded exploration; Return restores exact
  book ID, chapter, block, paragraph and reading context.
- **FOCUS_RESTORATION:** The source paragraph/semantic block regains focus, not
  merely the top of the chapter.
- **VISUAL_PROJECTION:** Typography, diagrams and synchronized board for sighted
  readers without making images the only source of meaning.
- **ACCESSIBLE_PROJECTION:** Heading/paragraph/diagram/position/game/main-line/
  variation/exercise/note block semantics and complete textual piece lists.
- **CANONICAL_ACTION:** `book_reader.open`, `book_reader.next_block`,
  `book_reader.open_chess_block`, `book_reader.return_to_text`,
  `book_reader.bookmark`.
- **MENU_PATH:** `Library > Books`; contextual `Book` and `Navigate` actions.
- **SHORTCUT_POLICY:** Reading/navigation keys are context-bound and remappable;
  Browse/Focus mode expectations are documented, never inferred silently.
- **ERROR_RECOVERY:** Invalid block/FEN/GameTree is isolated with source anchor;
  the rest of the book remains readable and the original artifact is retained.
- **COMPETITOR_EVIDENCE:** Lichess Blind Mode demonstrates that accessible and
  visual representations can coexist. Lichess Study and Chess.com Lessons show
  chapter/course discovery, but exact book-paragraph round-trip behavior was
  not practically proven. ChessBase documents training material display only.
- **DECISION:** `INSPIRE_BUT_IMPROVE`.

## 12. Training

- **USER_INTENT:** Attempt an exercise, receive controlled feedback, retry, ask
  for a hint/solution and continue without accidental answer disclosure.
- **ENTRY_POINT:** `Training`, book exercise, course lesson, GameTree position or
  teacher assignment.
- **WINDOW/PANE/DIALOG:** Training workspace with task text, Board/Move Input,
  feedback/status and navigation.
- **FOCUS_ENTRY:** Task instruction first, then the permitted answer control.
- **STATE:** Immutable task/source, attempt count, permitted command family,
  answer state, hint/solution policy, progress and navigation snapshot.
- **ACTIONS:** Attempt; submit; retry; hint; reveal solution when allowed;
  previous/next; analyse after completion if policy permits.
- **ESCAPE/RETURN:** Escape cancels an unsubmitted answer or returns to the
  source lesson. It does not reveal the solution.
- **FOCUS_RESTORATION:** Feedback returns to answer input for retry; completion
  moves to Next without losing the source lesson position.
- **VISUAL_PROJECTION:** Task board, progress, feedback and optional legal-move
  highlights governed by policy.
- **ACCESSIBLE_PROJECTION:** Task, side to move, concise correctness feedback,
  attempt count and explicit Hint/Solution/Next controls.
- **CANONICAL_ACTION:** `training.attempt`, `training.retry`, `training.hint`,
  `training.reveal_solution`, `training.next`, `training.return`.
- **MENU_PATH:** `Training`; exercise actions also exposed in the local menu.
- **SHORTCUT_POLICY:** Answer text is interpreted only by the task's explicit
  command policy. No global key reveals the solution accidentally.
- **ERROR_RECOVERY:** Invalid task/source is reported and skipped with progress
  intact; restart restores the last durable task/attempt state.
- **COMPETITOR_EVIDENCE:** Chess.com Lessons exposes structured lesson catalogs,
  challenges and mastery levels. ChessBase documents Training/Replay notation.
  SK Chess documents variation exploration. None proves the required
  accessibility/fail-safe solution policy.
- **DECISION:** `INSPIRE_BUT_IMPROVE`.

## 13. Menus

- **USER_INTENT:** Discover and execute every important action through a normal
  Windows keyboard/NVDA menu independent of memorized shortcuts.
- **ENTRY_POINT:** Alt, menu bar focus, or an explicit application-menu action.
- **WINDOW/PANE/DIALOG:** Native Windows menu hierarchy; context menus are
  secondary and never the only route for essential actions.
- **FOCUS_ENTRY:** Alt focuses the first/top-level menu with its accessible name
  and mnemonic; Left/Right changes top level, Down opens, Enter executes.
- **STATE:** Open menu path, enabled/checked/radio state and originating focus.
- **ACTIONS:** Alt; arrows; Enter; Esc; mnemonic; open submenu; announce disabled
  and checked states.
- **ESCAPE/RETURN:** Esc closes one submenu level, then the menu bar, restoring
  exact originating control and selection.
- **FOCUS_RESTORATION:** Every command/cancel returns to the invoking workspace
  unless the command intentionally opens a new focus scope.
- **VISUAL_PROJECTION:** Conventional Windows menu bar with visible mnemonics,
  checked/radio state and shortcuts.
- **ACCESSIBLE_PROJECTION:** Native Menu/MenuItem roles, concise names, state,
  shortcut and submenu information.
- **CANONICAL_ACTION:** Menu items reference live Action Registry IDs; menus do
  not implement separate command logic.
- **MENU_PATH:** `File`, `Game`, `Move`, `Position`, `Navigate`, `Engine`,
  `Database`, `Book`, `Training`, `View`, `Speak`, `Settings`, `Help` as
  applicable to the current workspace.
- **SHORTCUT_POLICY:** Mnemonics and registered accelerators come from the live
  action/keymap model. Hidden web handlers do not shadow native menu behavior.
- **ERROR_RECOVERY:** If an action becomes unavailable, it is disabled with a
  reason available in Help/status; menu failure never leaves keyboard focus in
  an invisible surface.
- **COMPETITOR_EVIDENCE:** ChessBase official help documents menu/ribbon paths
  and contextual shortcuts, but Reader 2017 robot showed mostly unnamed panes
  after Alt+F. SK Chess documents File/Speak/Game menu paths. Oleksii's human
  Issue #22 evidence rejected the previous Accessible Chess Alt menu.
- **DECISION:** `REJECT_ACCESSIBILITY_DEFECT` for competitor/old unnamed menu
  behavior; `ADOPT_AS_DEFAULT` for the native Windows contract above.

## 14. Help

- **USER_INTENT:** Learn the current command, menu path and shortcut without
  hearing stale or giant instructional text on every normal control.
- **ENTRY_POINT:** `Help > Accessible Chess Help`, F1, or contextual Help action.
- **WINDOW/PANE/DIALOG:** Searchable Help window/pane generated from the live
  Action Registry/keymap plus concise task-oriented guides.
- **FOCUS_ENTRY:** Help title/search or the current action's topic for contextual
  Help.
- **STATE:** Live locale, enabled actions, menu paths, current bindings,
  conflicts and topic/reading position.
- **ACTIONS:** Search; browse by task/menu; read action description/current
  shortcut; open Keymap; copy topic; return.
- **ESCAPE/RETURN:** Escape closes contextual Help and restores exact originating
  control. Full Help preserves its own reading/search position.
- **FOCUS_RESTORATION:** The invoking control regains focus; Help never injects
  long `aria-describedby` prose into it.
- **VISUAL_PROJECTION:** Search, TOC, task guide and compact key table.
- **ACCESSIBLE_PROJECTION:** Real headings, landmarks and concise action rows;
  current live bindings are spoken as data, not duplicated prose.
- **CANONICAL_ACTION:** `help.open`, `help.context`, `help.search`,
  `help.open_keymap`, generated from registered actions.
- **MENU_PATH:** `Help > Accessible Chess Help`, `Help > Keyboard Commands`.
- **SHORTCUT_POLICY:** F1 is the default contextual Help accelerator; current
  bindings displayed in Help always come from the live registry.
- **ERROR_RECOVERY:** Missing translation/topic falls back to a concise canonical
  action description and reports the gap without raw exceptions.
- **COMPETITOR_EVIDENCE:** SK Chess exposes menu actions and a concise keyboard
  guide. Lichess has a current Blind Mode tutorial. No evidence justifies stale
  hard-coded Help. Issue #22 rejects verbose focus descriptions.
- **DECISION:** `ADOPT_AS_DEFAULT`.

## 15. Keymap

- **USER_INTENT:** Inspect and safely remap actions while preserving Windows
  editing, menu and accessibility conventions.
- **ENTRY_POINT:** `Settings > Keyboard Commands` or Help action.
- **WINDOW/PANE/DIALOG:** Searchable keymap dialog with action, context, menu
  path, current/default binding, conflict state and Reset controls.
- **FOCUS_ENTRY:** Search field or current contextual action; capture mode is
  entered only by an explicit button.
- **STATE:** Versioned action IDs, contexts, bindings, defaults, reserved edit/
  menu chords, validation conflicts and persisted migration result.
- **ACTIONS:** Search/filter; inspect; start/cancel capture; assign/remove;
  resolve conflict; reset action/context/all; save/cancel; export/import profile.
- **ESCAPE/RETURN:** Escape exits capture first, then cancels dialog edits.
  Saving returns to the exact origin.
- **FOCUS_RESTORATION:** Validation focuses the conflicting binding. Successful
  save announces once and restores the invoking control.
- **VISUAL_PROJECTION:** Sortable action table with conflict/warning markers.
- **ACCESSIBLE_PROJECTION:** Semantic rows including action, context, menu path,
  binding and status; no repeated live announcement for valid rows.
- **CANONICAL_ACTION:** `keymap.open`, `keymap.capture`, `keymap.assign`,
  `keymap.remove`, `keymap.reset`, `keymap.save`, `keymap.cancel`.
- **MENU_PATH:** `Settings > Keyboard Commands`; Help links to the same model.
- **SHORTCUT_POLICY:** Bindings resolve by action ID and explicit context.
  Modifier-only bindings are invalid and recover safely. Reserved Windows edit
  semantics win inside editable controls. Competitor profiles are optional.
- **ERROR_RECOVERY:** Invalid persisted bindings are quarantined/reset with one
  concise warning; conflicts never crash startup or produce repeated success
  announcements.
- **COMPETITOR_EVIDENCE:** ChessBase exposes strongly contextual shortcuts;
  Lichess and SK Chess expose blind-specific keys. These justify profiles and
  contexts, not hard-coded global chords. Issue #22 records a raw modifier-only
  binding exception and live-region spam in the rejected candidate.
- **DECISION:** `INSPIRE_BUT_IMPROVE`.

## 16. Teacher / Classroom

- **USER_INTENT:** Let a blind teacher control one canonical chess lesson by
  keyboard/NVDA while sighted students receive a clear visual board and send
  hover/selection/answer feedback.
- **ENTRY_POINT:** `Teaching > Teacher Board`; later `Teaching > Classroom` only
  after core chess, data, engine, books and training gates are complete.
- **WINDOW/PANE/DIALOG:** Local Teacher Board first; visual student projection
  and accessible teacher controls share one TeachingSession. Remote/class/group
  panes are later adapters.
- **FOCUS_ENTRY:** Teacher workspace summary and last logical command family;
  dedicated Pointer Input is explicitly entered and distinct from Move Input.
- **STATE:** Canonical Position/GameTree plus separate PresentationState,
  TeacherPointer, annotations, student hover/selection history, mode,
  permissions and engine-visibility policy.
- **ACTIONS:** Type coordinate to move pointer immediately; highlight squares;
  draw/clear arrows; toggle coordinates; change teaching mode; receive student
  hover/selection; allow/deny student move; load FEN/PGN/book/database position;
  analyse and return.
- **ESCAPE/RETURN:** Escape leaves the active pointer/annotation/dialog scope
  without mutating chess state. Returning from Board/Engine/Book restores the
  exact lesson and student context.
- **FOCUS_RESTORATION:** Valid pointer coordinate auto-clears and retains Pointer
  Input for the next coordinate. Student events never steal teacher focus; they
  enter a concise accessible history/announcement channel.
- **VISUAL_PROJECTION:** Modern board, pointer, configurable highlights/arrows,
  coordinates, last move and permitted student interaction.
- **ACCESSIBLE_PROJECTION:** Teacher hears pointer square/piece, mode,
  annotation summary, student hover/selection and ordered pointer history; every
  visual state has meaningful text.
- **CANONICAL_ACTION:** `teacher.pointer_set`, `annotation.highlight`,
  `annotation.arrow`, `annotation.clear`, `teaching.set_mode`,
  `student.hover_observed`, `student.selection_observed`,
  `student.move_authorize`.
- **MENU_PATH:** `Teaching > Teacher Board`, `Teaching > Mode`,
  `Teaching > Pointer/Annotations`; Classroom/remote commands remain absent or
  disabled until their late product gate.
- **SHORTCUT_POLICY:** In Pointer Input, `f3` means point at f3 immediately; in
  Move Input it means a chess move only when legal; in Position Editor it edits
  the position. Context/family mismatches fail closed.
- **ERROR_RECOVERY:** Presentation/remote failure never corrupts Position or
  GameTree. Lost student transport preserves the local lesson and reports
  disconnected state. Personal-data features require privacy/deletion policy.
- **COMPETITOR_EVIDENCE:** Chess.com Analysis exposes a Classroom entry point,
  but the public robot did not prove its workflow or accessibility. Lichess
  Study proves study discovery only. No competitor evidence proves the required
  blind-teacher/sighted-student round trip; canonical Accessible Chess product
  requirements supply the invariant.
- **DECISION:** `INSUFFICIENT_EVIDENCE` for competitor behavior;
  `INSPIRE_BUT_IMPROVE` for the canonical Accessible Chess contract. This
  subsystem remains the final priority group after core completion.

## Adoption summary

- Default foundations: Playing, PGN/GameTree, Multi-game PGN, Search, Opening
  Reference, Opening Book, native Menus and live-registry Help.
- Contextual/professional adaptations: Engine Analysis and Database workspace.
- Improve beyond evidence: Engine Play lifecycle, Position Editor, Books,
  Training, Keymap and Teacher/Classroom.
- Rejected: unnamed/non-focusable menu/pane semantics, stale hard-coded Help,
  global shortcut collisions, security-bypass installation guidance and any
  inference that robot automation equals NVDA verification.
- Insufficient practical evidence: Scid, ChessX, activated Lichess Blind Mode,
  SK Chess executable behavior and full Classroom workflows.
