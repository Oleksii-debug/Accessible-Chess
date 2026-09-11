# Accessible Chess — V2 Ready Content + NVDA Hotkey Acceptance

Date: 2026-09-11
Status: binding product/release amendment requested by Oleksii during physical Version 2 acceptance
Scope: Version 2 Windows/NVDA and permanent product behavior afterward

## Why this amendment exists

Oleksii received the machine-green Version 2 candidate and found that important V2 surfaces cannot be meaningfully accepted as a real user product when the archive does not already contain books, training material, games and a usable sample Library/database. He also found that some keyboard shortcuts appear to execute but expose no resulting value/state to NVDA. Both findings are product/release gaps, not documentation polish.

The current machine-green artifact remains useful automated evidence, but it is not human-accepted. `NVDA_VERIFIED=NO`.

## 1. Ready-to-use content is part of the product

Books, Training, PGN and Library are not user-ready when the shipped application is an empty shell that requires the user to find or construct external material before those surfaces can be used or tested.

The exact Windows archive presented for Version 2 acceptance must contain an offline, lawful starter corpus that is discoverable and openable immediately after fresh extraction.

### Minimum Version 2 starter corpus

The packaged corpus must contain at least:

- 24 complete or substantial public-domain, permissively/open-licensed, or project-authored chess books/book-length learning materials;
- a usable Ukrainian-language starter collection for real NVDA reading and navigation;
- 100 ready lessons/exercises spanning beginner piece movement and coordinates, legal moves, tactics, mating patterns, defence, endgames, strategy and opening work;
- 200 curated instructional/sample games suitable for immediate PGN/GameTree study;
- at least one larger lawful PGN corpus suitable for Library import/search/browse testing;
- at least one prebuilt sample ACSDB/Library database built from lawful included material and immediately browsable/searchable after extraction;
- representative positions/FENs, structured diagrams, variation trees and annotated games where redistribution rights permit.

These are minimum acceptance numbers, not a long-term content ceiling. The finished product should grow to many more books, games, exercises, courses and teaching materials.

### Lawful redistribution and provenance

Every bundled item must have clear provenance and redistribution status. The package must include a source/provenance/license manifest sufficient to identify where the material came from and why it may be redistributed.

Do not bundle pirated commercial chess books, proprietary databases or copyrighted commentary without permission. Prefer public-domain material, permissive/open licenses and project-authored content.

### User-ready workflow

From a fresh extraction a user must be able to:

1. launch Accessible Chess;
2. find the supplied starter content through an accessible route;
3. open a supplied book and read it with NVDA;
4. navigate headings/sections/positions/games/variations as supported;
5. open a book position on the shared board and return to the same reading context;
6. open and traverse supplied PGN games;
7. open/browse/search the supplied sample Library/database;
8. launch supplied Training material/exercises;
9. use supplied content without an Internet download or manual content construction first.

The package/release chain must verify the corpus from a clean extracted archive. Existence on a developer machine, repository checkout or external Drive folder does not satisfy packaged acceptance.

Missing or undiscoverable bundled starter content is a Version 2 acceptance blocker when Books/Training/PGN/Library are presented as Version 2 capabilities.

## 2. A hotkey is incomplete when the result is silent

A keyboard shortcut is not accessibility-complete merely because the handler runs or internal state changes.

For every important user-facing shortcut, command or menu action, the application must expose concise deterministic accessible feedback containing the result or resulting state/value that matters to the user.

Examples:

- analysis depth changed -> expose/announce the resulting depth;
- MultiPV / analysis line count changed -> expose/announce the resulting line count;
- toggle changed -> expose/announce on/off or equivalent state;
- board/query command -> expose the requested chess information;
- navigation command -> expose the new logical location/context when needed;
- unavailable command -> expose a concise user-facing unavailable reason/state.

Never expose raw UCI, provider internals, traceback, local paths or debug text. User-triggered announcements must not turn into background live-region spam.

### User-found example

Oleksii reports that shortcuts he identifies as `Alt+1` / `Alt+2` for analysis depth / analysis-line behavior may execute but NVDA does not announce the resulting value. The exact live keymap must be verified before asserting which action each key performs. Regardless of the final mapping, the defect class is confirmed by user experience: **successful action + no accessible result feedback is incomplete**.

The fix must not be limited to those two shortcuts. Audit the full critical hotkey surface for the same silent-success defect class.

## 3. Acceptance test rule for shortcuts

Packaged Windows/NVDA acceptance must prove both halves for every critical shortcut:

1. `ACTION_OCCURRED`: the intended application state/action actually changed/executed; and
2. `ACCESSIBLE_RESULT_EXPOSED`: the resulting value/state/result is available immediately through the accessibility surface in a form NVDA can read.

A test that proves only event dispatch or handler execution is insufficient.

Help/keymap documentation must match live behavior. Focus after shortcut activation must remain logical and keyboard-safe.

## 4. Ownership and routing

Use the current Living Project Plan and live collision checks. Do not create duplicate Product implementations.

- W3 / User Workflows & Books: starter books/training corpus integration, Books/Training discoverability and ready-to-open journeys.
- W2 / Library & Data: prebuilt sample ACSDB/Library database, lawful PGN corpus publication, search/browse integrity.
- W4 / Windows Accessibility: accessible starter-content discovery/opening, shortcut result/state exposure, focus and NVDA semantics, packaged shortcut acceptance evidence.
- Relevant domain owners: provide structured result/state for their commands without creating a parallel speech/chess core.
- W5 / Integrator & Release: converge approved repairs/content, verify package contents, run full release chain and create one fresh candidate.

## 5. Release consequence

The previously machine-green Version 2 artifact is not human-accepted and must not be re-presented unchanged as sufficient final Version 2 validation.

Required sequence:

1. resolve bundled-content and silent-hotkey defects on non-duplicated Product lines;
2. converge through the current integration/release authority;
3. run focused tests plus full applicable regressions;
4. run the complete Windows package/release chain;
5. produce one fresh candidate containing the ready starter corpus and repaired accessibility behavior;
6. return that exact candidate to Oleksii for physical NVDA acceptance.

Until Oleksii accepts the exact fresh candidate:

- `HUMAN_ACCEPTED=NO`
- `NVDA_VERIFIED=NO`

This amendment does not weaken any existing accessibility, data-integrity, security, licensing, provenance, packaging or canonical-core requirement.