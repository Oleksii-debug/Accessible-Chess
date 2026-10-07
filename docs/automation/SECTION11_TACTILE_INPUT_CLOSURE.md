# Section 11 — tactile input, routing and device profiles

Canonical plan scope: Section 11, dependent on Sections 8–10.

## Repository-complete implementation in this candidate

- Typed routing/touch events are translated into existing canonical application commands through the live ActionRegistry and Version2 router.
- Board-square tactile input is navigation/read-only: file, rank and current-square commands are allowed; move activation, move submission, undo/redo and position mutation are not exposed by tactile profiles.
- Stale device events are fenced by a per-connection generation that changes on reconnect and profile switch.
- Multiple vendor-neutral layouts are represented through validated profiles: 8x8 White-bottom, 8x8 Black-bottom, 8x16 board-left, plus an 8x12 control profile. Additional hardware adapters may register more profiles without becoming chess-rule authorities.
- Layout geometry supports offsets and row/column strides; cells outside the exact board lattice fail closed.
- Routing, touch and named-button capabilities are validated against live device capabilities before dispatch.
- Device/profile selection, default profile and auto-reconnect preference are persisted in bounded UTF-8 JSON with atomic replacement and symlink/non-regular target rejection.
- Reconnect refuses an incompatible saved profile instead of guessing.
- Version2Application composes the controller at startup using a durable settings path next to the existing application progress roots.
- Version2 tactile ingress is allowed only on the visible Board route, on the native UI thread and with no active dialog.
- Media, Classroom and Universal Chess Agent integration is intentionally absent, as required by Section 11.5; that cross-integration belongs to Section 36.

## Qualification

Focused local executable contract before publication: tests/test_tactile_input.py = 21/21 PASS.

Canonical GitHub qualification is defined by .github/workflows/section11-tactile-input-profiles.yml and runs on Ubuntu 22.04 and Windows 2025:

- exact-head/bounded-scope check;
- Python compile for the new tactile layer and Version2 composition;
- tactile input/profile/persistence/reconnect regressions;
- Version2 tactile ingress fences;
- canonical tests.test_version2_application regression;
- explicit static mutation-safety oracle.

## Dependency and terminal closure truth

This successor completes the repository-controllable Section 11 implementation without inventing a second tactile display, hardware, Position, GameTree, Books, Training or chess-rules authority.

The canonical hard predecessors are now accepted and durably terminal:
- Section 8 — refreshable tactile graphics core;
- Section 9 — DotPad hardware adapter, physically converged onto Section 8;
- Section 10 — tactile synchronization, accepted combined parent `56180eb6f1b033f4a5a99c62426233d530d9dcc7`.

The frozen Section-11 implementation from `e804ddca39303a965c0600b604d883a852dcbdd3` is preserved: tactile input, focused tests and safety contract are carried unchanged. The only Product overlap, `acs/version2_application.py`, is dependency-converged by retaining the accepted Section-10 tactile graphics/synchronization composition and adding the frozen Section-11 input controller composition, constructor setting path and visible-Board/dialog/UI-thread dispatch fence.

The terminal workflow also reruns the accepted Section-10 V2 tactile-wiring regression so the shared composition boundary fails closed if either authority is lost.

SECTION_11_STATE=TERMINAL_CANDIDATE_ON_ACCEPTED_SECTION_10

Physical tactile hardware handling and manual NVDA evidence remain final whole-product acceptance evidence and do not block this intermediate closure under Simplified Section Closure Protocol v3.

After integration, post-merge readback plus the durable `SEQUENTIAL_CLOSURE_STATE.md` row are the terminal receipt. Ordinary workers must not re-enter Section 11 except for a concrete demonstrated regression, invalidated closure evidence, materially changed acceptance contract, or later integration break.
