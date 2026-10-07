# Section 10 Closure Audit — tactile synchronization

Canonical plan scope:

- 10.1 PGN/GameTree -> tactile board.
- 10.2 Book -> Board -> tactile -> Return.
- 10.3 Training/exercise -> tactile view and refresh after answers.
- 10.4 canonical Position/GameTree navigation synchronizes tactile state.
- 10.5 accessible tactile status and commands.

Hard dependencies in the canonical plan: Sections 6–9.

## Owner-directed closure authority

The repository owner explicitly directed this execution to finish Section 10 in
one run and, after completion, mark it fully closed so ordinary workers do not
return to it.

The repository's Simplified Section Closure Protocol v3 already permits
owner-directed intermediate/out-of-order closure when the Section's
repository-controllable scope is complete and no known failing acceptance check
remains. The live ledger uses the same mechanism for Section 6 and Section 9.

For this Section-10 closure:

- Section 6 is already `DONE — TERMINAL`;
- Section 9 is already `DONE — TERMINAL`;
- the exact Section-8 tactile-core candidate
  `7a4d14d68642a5d4fb81bbf5474525d1743d71ac` is frozen and its dedicated
  run `37677699807` completed successfully on Ubuntu and Windows;
- Section 7 is lawful-real-corpus qualification for the Formats/Library/Books
  foundation. It supplies no runtime API or alternate state authority consumed
  by Section 10;
- Section 10 is therefore closed against the frozen Section-8 interface instead
  of mutating or falsely completing Section 7/8 on their behalf.

If later accepted predecessor integration demonstrably makes the frozen
Section-8 interface incompatible with this Section-10 implementation, that
concrete incompatibility is a valid reopen condition. Mere desire to refactor,
polish, duplicate, or revisit this Section is not.

## Canonical implementation

This lineage composes existing canonical product owners with the actual
Section-8 `TactileGraphicsController`.

`acs/tactile_sync.py` provides one synchronization authority:

- PGN uses `PgnWorkspace.current_game()` and immutable `GameTreeCursor`;
  Section 8 resolves the tactile position through existing canonical GameTree
  legality;
- Book uses `BookBoardView.current_fen` and never moves or reconstructs the
  exact `ReadingLocation` return origin;
- Training uses `ExerciseSession.current_fen` and canonical attempt state;
- generic Position/FEN is parsed through canonical `PositionState` before
  Section-8 projection;
- presentation/device failure records `tactile.status.refresh_failed` and
  cannot mutate canonical Board, PGN, Book or Training state.

`acs/version2_application.py` completes product reachability:

- the V2 application owns one Section-8 controller and one Section-10
  synchronizer;
- absence of configured physical hardware falls back to the deterministic
  Section-8 simulator and does not block application startup;
- canonical Board position transitions refresh tactile state after the Board
  action succeeds;
- PGN Board open/navigation and PGN workspace navigation refresh from canonical
  GameTree state;
- Book Board open/update refreshes after canonical Book Board projection while
  retaining exact Return authority;
- Training refreshes after canonical Training command completion, including
  answer attempts;
- automatic synchronization is an observer side effect: tactile failure never
  rolls back product truth and never injects unsolicited NVDA status chatter
  into ordinary navigation.

Accessible user commands are part of the central V2 ActionRegistry and native
Settings menu:

- `tactile.status` — read semantic synchronization state;
- `tactile.refresh` — refresh tactile state from the current canonical
  Board/PGN/Training context.

Both commands publish localized Ukrainian/English status through the existing
accessible application status-event path.

No second chess-rules authority, GameTree, Book navigation engine, Training
correctness engine, tactile geometry algorithm, device SDK owner, or tactile
input/routing authority is introduced by Section 10.

## Acceptance evidence

`tests/test_section10_tactile_sync.py` covers:

- exact Section-8 controller composition;
- canonical Position -> tactile scene;
- PGN/GameTree cursor -> updated tactile scene;
- Book tactile projection without changing exact Return origin;
- Training refresh after accepted and rejected answers;
- failing tactile output cannot mutate canonical Training or advance the
  Section-8 scene;
- strict command/status behavior.

`tests/test_section10_v2_tactile_wiring.py` covers:

- V2 ActionRegistry and native Settings-menu reachability;
- manual accessible refresh/status;
- automatic Board refresh after canonical position transitions;
- automatic PGN Board open/navigation refresh;
- automatic Training refresh after an answer;
- tactile-output failure does not roll back a successful Board action.

The focused Section-10 workflow compiles all touched integration modules and
runs on Ubuntu and Windows:

- retained Section-8 tactile-core tests;
- both focused Section-10 test modules;
- retained full-product native-menu tests;
- retained Version-2 composition-profile tests.

Supporting machine evidence:

- the frozen Section-8 predecessor's exact dual-OS run `37677699807` is
  terminal SUCCESS on Ubuntu and Windows;
- the earlier bounded Section-10 synchronization implementation run
  `37677193580` completed successfully on Ubuntu and Windows before this
  lineage was rebound to the real Section-8 controller;
- the final exact-head Section-10 hosted run is recorded in the PR/terminal
  ledger receipt. If GitHub runners remain queued/unstarted, that is recorded
  as hosted-runner unavailability, never misreported as GREEN, under Simplified
  Section Closure Protocol v3.

## Terminal closure state

Repository-controllable Sections 10.1–10.5 are complete.

`SECTION_10_DONE=YES_OWNER_DIRECTED_OUT_OF_ORDER`

`SECTION_10_1_DONE=YES`

`SECTION_10_2_DONE=YES`

`SECTION_10_3_DONE=YES`

`SECTION_10_4_DONE=YES`

`SECTION_10_5_DONE=YES`

`NORMAL_REENTRY=FORBIDDEN`

`REOPEN_ONLY_ON_CONCRETE_REGRESSION_INVALIDATED_EVIDENCE_CHANGED_ACCEPTANCE_OR_DEMONSTRATED_PREDECESSOR_INCOMPATIBILITY`

After merge, the post-merge readback and `SEQUENTIAL_CLOSURE_STATE.md` row are
the durable terminal receipt. Ordinary workers must skip Section 10.
