# Section 10 Closure Audit — tactile synchronization

Canonical plan scope:

- 10.1 PGN/GameTree -> tactile board.
- 10.2 Book -> Board -> tactile -> Return.
- 10.3 Training/exercise -> tactile view and refresh after answers.
- 10.4 canonical Position/GameTree navigation synchronizes tactile state.
- 10.5 accessible tactile status and commands.

Hard dependencies: Sections 6–9.

## Canonical implementation candidate

This lineage is the single Section-10 successor over the live Section-8 tactile
core. PR #2393 is targeted at the frozen Section-8 candidate
`7a4d14d68642a5d4fb81bbf5474525d1743d71ac`.

`acs/tactile_sync.py` composes canonical product owners with the actual
Section-8 `TactileGraphicsController`:

- PGN uses `PgnWorkspace.current_game()` plus immutable `GameTreeCursor`;
  Section 8 resolves the position through the existing canonical legality
  authority.
- Book uses `BookBoardView.current_fen` and never moves or reconstructs the
  exact `ReadingLocation` return origin.
- Training uses `ExerciseSession.current_fen` and canonical attempt state.
- generic Position/FEN is parsed through canonical `PositionState` before
  Section-8 projection.
- display failure records `tactile.status.refresh_failed` and cannot mutate
  canonical PGN, Book, Training or Board state.

`acs/version2_application.py` completes the product wiring:

- the V2 application owns one Section-8 controller and Section-10 synchronizer;
- absence of configured physical hardware falls back to the deterministic
  Section-8 simulator, so tactile hardware is never a startup blocker;
- canonical Board position transitions refresh tactile state after the Board
  action has succeeded;
- PGN Board open/navigation and PGN workspace navigation refresh from the
  canonical GameTree owner;
- Book Board open/update refreshes tactile state only after canonical Book Board
  projection succeeds, preserving exact Return authority;
- Training refreshes after canonical Training command completion, including
  answer attempts;
- automatic tactile refresh is an observer side effect: a tactile failure never
  rolls back or replaces canonical chess/product state and does not inject noisy
  unsolicited NVDA announcements into ordinary navigation.

Accessible user commands are now part of the central ActionRegistry and V2
native Settings menu:

- `tactile.status` — reads the current semantic synchronization state;
- `tactile.refresh` — refreshes from the current Board/PGN/Training context.

The commands publish localized Ukrainian/English status announcements through
the existing accessible application status event path.

No chess rules, alternate GameTree, tactile geometry algorithm, device SDK,
hardware connection state or tactile input/routing authority is created here.
Those remain Section 1/2, Section 8, Section 9 and Section 11 ownership.

## Automated evidence

`tests/test_section10_tactile_sync.py` covers the presentation-neutral contract:

- exact Section-8 port/controller composition;
- canonical Position -> tactile scene;
- PGN/GameTree cursor -> updated tactile scene;
- Book tactile projection without changing exact Return origin;
- Training tactile refresh after accepted and rejected answers;
- failing tactile display cannot mutate canonical Training or advance the
  Section-8 scene;
- strict command/status behavior.

`tests/test_section10_v2_tactile_wiring.py` covers the product composition:

- V2 ActionRegistry and native Settings-menu reachability;
- manual accessible refresh/status;
- automatic Board refresh after a canonical position transition;
- automatic PGN Board open/navigation refresh;
- automatic Training refresh after an answer;
- tactile output failure does not roll back a successful Board action.

The focused Section-10 workflow compiles all touched integration modules and
runs, on Ubuntu and Windows:

- retained Section-8 tactile-core tests;
- both Section-10 focused test modules;
- retained full-product native-menu tests;
- retained Version-2 composition-profile tests.

## Live dependency truth

Section 10 must **not** be recorded DONE while its hard predecessors are not all
durably DONE.

At this audit revision the live GitHub closure registry records:

- Section 6 = `DONE — TERMINAL`;
- Section 9 = `DONE — TERMINAL`, accepted DotPad adapter candidate
  `6c596230f79fa86c5679844fd18184d64ff234ee`, integrated as
  `5119a4cca81e4563cc5edcf263bb639c5b045b6a`;
- Section 8 = `CANDIDATE_FROZEN`, not DONE, because its own hard predecessor
  chain is not closed;
- Section 7 has no durable DONE row;
- Section 2 is currently `REOPENED — REPAIR QUALIFYING`, and Sections 3–5 are
  not all durably recorded DONE, which is also the explicit blocker recorded by
  the Section-8 owner.

Therefore a terminal `Section 10 = DONE` or `DO NOT REOPEN` record would be
false evidence even though the repository-controllable Section-10 implementation
itself is now complete.

Current state:

`SECTION_10_IMPLEMENTATION=CANDIDATE_FROZEN_COMPLETE`

`SECTION_10_DONE=NO_BLOCKED_ON_SECTION_7_AND_SECTION_8_TERMINAL_DEPENDENCIES`

Ordinary workers must not reimplement or polish this Section-10 candidate.
Source mutation is justified only by a concrete qualification failure or a
demonstrated incompatibility with the eventually accepted Section-8 predecessor.
Once Sections 7 and 8 are durably DONE, qualify the exact retained candidate,
integrate it, perform post-integration readback, update
`SEQUENTIAL_CLOSURE_STATE.md`, and only then apply the terminal no-return lock.
