# Section 10 — tactile synchronization closure audit

## Canonical scope

Canonical Drive Section Plan:

**SECTION 10 — Тактильна синхронізація з Formats, Books і Training**

Dependencies: Sections 6–9.

Required subsections:

- 10.1 PGN/GameTree -> tactile board.
- 10.2 Book -> Board -> tactile -> Return.
- 10.3 Training/exercise position -> tactile view and refresh after answer.
- 10.4 Any canonical Position/GameTree navigation synchronizes tactile state.
- 10.5 Accessible tactile status and commands.

Stockfish, Media and Classroom are explicitly not hard dependencies for this
Section.

## What this lineage implements

This branch introduces one presentation-neutral synchronization controller:
`acs/tactile_sync.py`.

It deliberately reuses existing canonical owners:

- PGN/GameTree position: `Version2PgnCommands.current_fen()`, whose FEN is
  derived through canonical GameTree legality;
- Book Board position: `BookBoardView.current_fen`, retaining the exact
  `ReadingLocation` origin owned by `BookBoardWorkflow`;
- Training position: `ExerciseSession.current_fen`, which changes only through
  the canonical Training session;
- generic canonical Position/FEN: revalidated through `chesscore.Board`.

The controller forwards canonical FEN to a narrow `TactilePositionSink`.
That sink is an adapter seam only.  It does not define a second tactile scene,
device protocol or chess authority.  Sections 8/9 remain the owners of
TactileDisplayPort/TactileScene, simulator and real hardware transport.

Stable semantic command IDs are exposed for keyboard/screen-reader presentation:

- `tactile.status`;
- `tactile.refresh_position`;
- `tactile.refresh_pgn`;
- `tactile.refresh_book`;
- `tactile.refresh_training`.

A provider failure records `tactile.status.refresh_failed` and never rolls
back, edits or substitutes canonical chess/Book/Training state.

## Focused evidence

`tests/test_section10_tactile_sync.py` covers:

- canonical Position refresh and rejection of non-canonical FEN;
- PGN/GameTree cursor movement -> changed canonical tactile FEN;
- Book Board view -> tactile FEN while exact Book return origin remains intact;
- Training position before and after a correct answer;
- Training refresh after an incorrect answer without false board mutation;
- tactile provider failure without canonical Training mutation;
- strict accessible command/status surface and wrong-source rejection.

`.github/workflows/section10-tactile-sync.yml` runs the focused contract on
Ubuntu and Windows.

## Closure truth for this execution

This is material Section-10 implementation, but **Section 10 is not authorized
as DONE yet** because its canonical hard dependencies are not durably closed.

Live `SEQUENTIAL_CLOSURE_STATE.md` at the start of this work records:

- Section 0 = DONE;
- Section 1 = CANDIDATE_FROZEN / QUALIFYING;
- Sections 6–9 do not yet have durable DONE evidence.

The accepted product tree also contains no Section-8/9 tactile core or hardware
adapter and live GitHub search found no pre-existing tactile / Section-8 /
Section-9 / Section-10 PR or branch to reuse.

Therefore this lineage must remain a dependency-blocked Section-10 candidate
and MUST NOT write a false `Section 10 = DONE` row or terminal no-return lock.
When Sections 6–9 are honestly DONE, converge this controller onto their exact
accepted lineage, adapt `TactilePositionSink` to the accepted Section-8/9 port,
run exact-head focused qualification, integrate, and only then write terminal
Section-10 DONE.

`SECTION_10_IMPLEMENTATION=PREPARED`

`SECTION_10_DONE=NO_BLOCKED_ON_SECTIONS_6_7_8_9`

`MANUAL_NVDA_ACCEPTANCE=FINAL_PRODUCT_ONLY_PER_AGENTS_V3`
