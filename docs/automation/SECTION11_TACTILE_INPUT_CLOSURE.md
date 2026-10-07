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

## Dependency and closure truth

This candidate completes the repository-controllable Section 11 implementation without inventing a second tactile display, hardware, Position, GameTree, Books, Training or chess-rules authority.

However, the canonical Section plan makes Sections 8, 9 and 10 hard predecessors. At candidate creation time those Sections are not recorded DONE in SEQUENTIAL_CLOSURE_STATE.md and no accepted tactile display/hardware/synchrony lineage is present in the live product ancestry.

Therefore the only honest durable state before predecessor convergence is:

SECTION_11_STATE=CANDIDATE_FROZEN_PENDING_SECTIONS_8_10

Do not mutate this candidate for polishing or parallel reimplementation. Re-open its source only for a concrete qualification failure or an actual integration incompatibility discovered while converging accepted Sections 8–10. Once all three predecessors are accepted, reconverge this exact implementation over the accepted Section 10 predecessor, run the same qualification, integrate, perform post-integration readback, and then change Section 11 to terminal DONE.

Physical tactile hardware evidence is final acceptance evidence and is not used to claim intermediate repository completion under Simplified Section Closure Protocol v3.
