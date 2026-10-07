# Section 8 Closure Audit — Refreshable Tactile Graphics Core

Canonical plan: **SECTION 8 — Refreshable Tactile Graphics Core**.

Canonical plan revision at audit start:
`AHj4eMRgmsXXWqlCWeR_5F-46Ih3m_cfXBnu0AmnMUpGQPqYY1C4kuw6vk_it1ujhxcUx6rkI7tx6mcmEDrW7XxWNQQ2k4X3Ko91JiCnng`.

## Fixed acceptance boundary

Section 8 contains exactly these product requirements:

1. Generic `TactileDisplayPort` and vendor-neutral `TactileScene`.
2. Simulator/mock driver.
3. Canonical `Position` -> tactile full-board/focus-view projection.
4. Refresh on canonical `Position` and `GameTree` navigation.
5. Tactile exploration must not mutate the chess `Position`.

Hard dependency declared by the canonical plan: Sections 0-7. The terminal
closure run must re-read the live dependency ledger before writing `DONE`.

## Implementation mapping

- `acs.tactile_graphics.TactileDisplayPort` is the vendor-neutral semantic
  output port. It contains no device discovery, geometry negotiation, driver
  status, settings, or vendor API.
- `TactileScene` is immutable and self-validating. It carries one canonical
  `PositionState` FEN, an exact 64-cell white-side full-board view, a bounded
  local focus view, sequence identity, and refresh source.
- `TactileSimulator` is the Section-8 in-memory simulator/mock driver.
- `project_tactile_scene()` projects only the existing canonical
  `PositionState`; it does not implement chess rules.
- `position_for_gametree_cursor()` and
  `TactileGraphicsController.on_gametree_navigation()` reuse
  `validate_game_legality()` plus the existing immutable `GameTreeCursor`.
  Section 8 does not parse SAN, apply chess moves, or create a second GameTree
  authority.
- `refresh_position()` / `on_position_navigation()` always emit a fresh scene.
- `explore()` rebuilds from the detached FEN stored in the current immutable
  scene. It can change tactile focus only. The chess position fingerprint must
  remain byte-identical.
- Controller state commits only after the output port accepts a scene, so a
  failing adapter cannot advance the semantic tactile state.

## Explicit non-goals / later Sections

- **Section 9:** physical TactileFrame/other hardware adapters, connect/
  disconnect, capabilities, device geometry/status/errors/settings.
- **Section 10:** Books, Formats, Training synchronization.
- **Section 11:** tactile input, routing, device profiles.
- No manual NVDA or physical tactile-device evidence is required for this
  intermediate Section under Simplified Section Closure Protocol v3.

## Automated acceptance

`tests/test_section8_tactile_graphics_core.py` proves the 64-square projection,
focus view, simulator history, Position/GameTree refresh, branch navigation,
non-mutating exploration, fail-closed unprovable positions, and transactional
controller state on invalid input/output-port failure.

`.github/workflows/section8-tactile-graphics-core.yml` executes Section-8
tests on Ubuntu 22.04 and Windows 2025 and reruns adjacent canonical Position
and GameTree regressions.

## Closure rule

Do not write `DONE` from this audit alone. Terminal closure requires:

1. live confirmation that the plan's Section 0-7 hard dependency condition is
   satisfied;
2. exact candidate qualification using all Section-8 checks actually available
   to autonomous workers;
3. canonical integration and post-merge readback;
4. durable `SEQUENTIAL_CLOSURE_STATE.md` update naming accepted evidence.

After `DONE`, ordinary workers must skip Section 8. Reopen only for a concrete
regression, invalid closure evidence, materially changed acceptance contract,
or later integration that demonstrably breaks Section 8.
