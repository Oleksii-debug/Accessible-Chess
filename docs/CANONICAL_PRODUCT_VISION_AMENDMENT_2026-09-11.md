# Canonical Product Vision Amendment — 2026-09-11

This amendment records Oleksii's binding product decision made during physical Version 2 testing.

## Product must include meaningful ready content

Accessible Chess is not only a set of parsers, readers and empty Library surfaces. When Books, Training, PGN and Library are part of a user release, the product must include enough lawful ready-to-open material for a user to start reading, studying, training, browsing games and testing database workflows immediately after extraction.

Version 2 minimum acceptance content is specified in `docs/V2_READY_CONTENT_AND_NVDA_HOTKEY_ACCEPTANCE_2026-09-11.md`: dozens of lawful books/learning materials, Ukrainian starter material, exercises, instructional/sample games, a larger lawful PGN corpus, a prebuilt sample ACSDB/Library database, and representative positions/variations. All bundled material requires provenance and redistribution rights.

The long-term product should continue growing a substantial built-in accessible chess-learning corpus rather than forcing blind users to source every book, game collection or training example themselves.

## Keyboard action must communicate its result

For a blind user, a hotkey that changes an internal value but produces no accessible result is not a complete control. Important user-triggered actions must expose the resulting value/state/result concisely to NVDA or the equivalent accessibility surface.

This requirement applies systematically to engine settings, analysis depth, MultiPV/line count, toggles, board queries, navigation and other command families. It must not be implemented as uncontrolled background speech spam, and must never expose raw engine/provider/debug internals.

## Version 2 acceptance

The machine-green candidate already delivered to Oleksii is not human-accepted because physical testing exposed the missing ready-content gate and silent-hotkey defect class. `NVDA_VERIFIED=NO` until a fresh candidate containing the resolved requirements passes the normal automated release chain and Oleksii personally accepts that exact build.