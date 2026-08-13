# Accessible Chess — Stage 1 Specification

Status: ACTIVE. Scope is locked to Stage 1 until user NVDA testing and explicit approval.

## Goal
Deliver a usable Windows chess application for a blind user with keyboard-first navigation, position setup, Stockfish analysis, and play versus Stockfish. Do not expand into chess databases, CBH/CBV/CBF, online accounts, matchmaking, or other later-stage modules.

## Interaction model
The application must support three parallel navigation paths:

1. Tab / Shift+Tab through focusable native controls.
2. Web-like semantic navigation. Prefer real accessibility semantics where the chosen Windows UI technology supports them. If native NVDA browse-mode H/B/I navigation is not available, implement application-level H/Shift+H, B/Shift+B and I/Shift+I commands that move between headings, buttons and input controls and announce the target.
3. Global shortcuts for frequent chess actions.

Escape exits an interaction submode. Enter/Space activates a control or selects/moves a board piece. F6 cycles major regions when useful.

## Main regions and heading order
1. Інформація про гру / Game information
2. Список ходів / Move list
3. Білі фігури / White pieces
4. Чорні фігури / Black pieces
5. Стан гри / Game status
6. Останній хід / Last move
7. Введення ходу / Move input
8. Аналіз Stockfish / Stockfish analysis
9. Дошка / Board
10. Дії / Actions

## Board
- Standard starting board with Ctrl+N.
- Empty-board command.
- 64-square logical board navigated with plain arrow keys.
- On each square announce coordinate and content, e.g. `e 4, білий пішак` / `e 4, white pawn`, or `e 5, порожньо`.
- No table-navigation modifier keys are required.
- No wraparound at board edges.
- Piece move from board: Enter/Space on source selects it, navigate to target with arrows, Enter/Space attempts the legal move. Escape cancels selection.
- Illegal move gives a concise semantic message and does not silently change state.

## Move input
The move input accepts Lichess/SAN-like commands:
- e4
- Nf3
- Bc4
- O-O
- O-O-O
- promotions and disambiguation where required.

Pawn moves use no piece letter. Internal parser remains language-independent; UI announcements are localized.

Command-mode entries may use a leading colon to avoid collisions with chess notation. Required commands include:
- `:u` undo
- `:r` redo
- `:l` announce last move
- `:w` set white to move
- `:b` set black to move
- `:clear` clear board
- `:start` restore standard start
- `:me` announce user's clock
- `:op` announce opponent clock
- `:engine` toggle Stockfish

## Game mode and analysis mode
### Game mode
- Strict legal alternation of side to move.
- Normal chess legality including castling, en passant, promotion, check, mate and stalemate.

### Analysis/composition mode
- User may explicitly set white or black to move.
- Support a training option that preserves the selected side to move across manual moves, allowing several moves by one color for demonstration/training.
- Composition setup may contain promoted material or more than the normal number of a piece. Standard-game legality validation and composition validation are separate.

## Position editor
- Clear board and set arbitrary position without graphical drag-and-drop.
- Text format uses `W:` and `B:` sections with piece letters and coordinates, e.g. `W: K g1 Q d1 R a1 R f1 B c4 N f3 P e4 B: K g8 Q d8 N f6`.
- Multiple same-type pieces are allowed in composition/analysis mode.
- User can set side to move independently.
- FEN import is part of Stage 1 and must restore board, side to move, castling rights and en-passant state where valid.
- Full PGN/database architecture is explicitly out of scope for Stage 1. Existing basic PGN code may remain but must not drive scope expansion.

## Move history and position summaries
Move list uses accessible spoken formatting, for example:
`1. e 4, e 5.`
`2. кінь f 3, кінь c 6.`

White pieces and Black pieces regions list pieces by type and coordinates. Example:
`король: g 1`
`ферзь: f 3`
`тура: a 1, f 1`

Last move is separately exposed and available by shortcut.

Undo/redo must keep board, side-to-move, result, clocks, review state and engine-analysis state consistent.

## Stockfish analysis
- Toggle engine globally.
- Analysis uses current view position and selected side to move.
- MultiPV = 5.
- Alt+1 through Alt+5 announce the corresponding current PV line.
- A separate command announces depth and evaluation; do not overload Alt+1..5 with depth.
- Full principal variation is available in the Stockfish analysis region.
- Engine may think continuously in analysis mode.
- Any position change invalidates old displayed/readable analysis.
- Async results must be published only if both analysis generation/job ID and analyzed FEN still match current view position.
- Never speak a stale engine line for a different position.

## Play versus Stockfish
Game setup dialog includes:
- Color: White / Black / Random.
- Strength: a stable user-facing level scale mapped to supported Stockfish strength parameters.
- Time control: no clock plus common presets and a custom option.
- Start game button.

During the game expose:
- player/opponent
- color
- both clocks
- side to move
- game state
- moves
- last move
- board

Actions:
- Take back. Against Stockfish this should normally restore the user's turn by undoing the engine move and the user's preceding move, unless only one reversible ply exists.
- Offer draw.
- Resign with confirmation.

Required clock shortcuts include user time and opponent time. Clock state must remain correct across undo/redo and game end.

## Sounds
Do not use arbitrary system beeps as chess sounds.

Required sound events:
- move
- capture
- check
- castle
- promotion
- illegal move/error
- game start
- game end
- clock tick

Sound assets must have documented, redistribution-safe licensing and credits. Settings include master volume, chess sounds on/off, clock tick on/off, and tick policy: user's turn / opponent turn / always / final-N-seconds option.

## Localization and notation
Stage 1 ships with Ukrainian and English UI/announcements from a centralized localization layer. No hard-coded user-facing strings scattered through logic.

Notation/readout profiles:
- short SAN (`Nf3`)
- Ukrainian literal (`кінь f 3`)
- English literal (`knight f 3`)

Coordinates should support spaced reading (`f 3`) for screen-reader clarity.

## Menu and shortcuts
Native Alt menu structure:
- Файл / File
- Гра / Game
- Дошка / Board
- Аналіз / Analysis
- Налаштування / Settings
- Довідка / Help

Ctrl+N starts a new standard game/position. Existing useful shortcuts may be preserved if they do not conflict with the locked Stage 1 interaction model.

## Accessibility acceptance
Do not claim `NVDA VERIFIED` from Linux, Xvfb, unit tests, or generic UI automation.

Allowed status labels include:
- SPECIFIED
- IMPLEMENTED
- AUTOMATED TEST PASS
- WINDOWS TEST PASS
- NVDA VERIFIED
- NOT IMPLEMENTED
- BLOCKED

Release-candidate exit condition is `WAITING FOR USER NVDA TEST`. Stage 2 must not start until the user tests the Windows build with NVDA and explicitly approves Stage 1.

## Out of scope until approval
- CBH/CBV/CBF
- ChessBase database integration
- large PGN database workflows
- online accounts/authentication
- online friend play/matchmaking
- server infrastructure
- later-stage library/search/database features
