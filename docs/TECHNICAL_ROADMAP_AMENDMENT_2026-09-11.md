# Technical Roadmap Amendment — 2026-09-11

This amendment is binding alongside `docs/TECHNICAL_ROADMAP.md` and `docs/CANONICAL_PRODUCT_VISION_UA.md` until its requirements are folded into those canonical documents.

## Version 2 user-ready content gate

Version 2 is not accepted as a real Books/Training/PGN/Library product if the release archive contains the functionality but no meaningful ready-to-open corpus. The packaged Windows candidate must include the lawful starter content defined in `docs/V2_READY_CONTENT_AND_NVDA_HOTKEY_ACCEPTANCE_2026-09-11.md`, and fresh-extraction testing must prove that the content is discoverable and opens through the real application.

## Version 2 NVDA hotkey result gate

A user-facing shortcut is incomplete when it performs an action but does not expose its resulting state/value/result through the accessibility surface. Packaged accessibility acceptance must prove `ACTION_OCCURRED + ACCESSIBLE_RESULT_EXPOSED` for critical shortcuts. This applies to analysis depth, MultiPV/line-count controls, toggles, queries, navigation and analogous commands.

Oleksii’s report concerning silent `Alt+1` / `Alt+2` behavior is a user-found defect example; the exact live key mapping must be verified before repair. The defect class must be audited across the critical shortcut surface rather than patched only for two keys.

## Release effect

The existing machine-green candidate is not human-accepted. `HUMAN_ACCEPTED=NO` and `NVDA_VERIFIED=NO`. Fixes/content must converge into one fresh candidate followed by the full release chain and physical NVDA acceptance.