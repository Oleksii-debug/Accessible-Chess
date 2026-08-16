# WordDeck continuous QA and development plan

This plan governs work on the isolated `worddeck-bootstrap` branch. Never modify `main` as part of WordDeck work.

## Run order

Every development pass should use this order:

1. Read the current branch head and latest Windows Actions result.
2. Fix any build, self-test, runtime, data-integrity, accessibility, or persistence regression before adding features.
3. Continue translation QA from the last recorded position.
4. Run shortcut and core-function regression checks.
5. Implement at most one coherent usability or learning improvement per pass unless a blocker requires more.
6. Keep the single-file self-contained Windows build green.

## Translation QA: all 3308 Oxford entries

The target is an exhaustive review, not spot checking.

- Review every entry in source order, retaining its Oxford entry ID and CEFR level.
- Check the English lemma/phrase, Ukrainian spelling, grammatical category implied by the lemma, and whether the Ukrainian side covers the common learner-relevant sense without becoming misleadingly broad.
- For polysemous or suspicious entries, verify the English meaning and Ukrainian equivalent against reliable dictionary/reference sources rather than guessing.
- Distinguish `verified`, `corrected`, and `needs-second-pass` entries in a durable QA ledger under `WordDeck/QA/` so later runs resume exactly where the previous run stopped.
- A second pass must revisit every `needs-second-pass` item before the translation QA is declared complete.
- Keep Ukrainian wording concise enough for a flash card. Prefer a small number of high-value equivalents over an uncontrolled list of synonyms.
- After any dictionary correction, regenerate the embedded resource consistently and rerun the 3308-entry/CEFR self-test.
- Never claim all translations are verified until the ledger accounts for all 3308 entries and there are zero unresolved second-pass items.

## Shortcut QA

All 16 current actions must remain configurable:

- next random word;
- previous word;
- reveal translation;
- repeat current English word;
- open shortcut settings;
- open help;
- switch to decks 1 through 5;
- move the current word to decks 1 through 5.

Expected UX:

- The settings window presents one row per function with the currently assigned shortcut.
- Keyboard focus starts in the action list.
- Enter on a selected action opens shortcut capture.
- The user presses the desired key combination directly; no text entry is required.
- Esc cancels capture.
- Duplicate assignments are rejected with a clear message.
- Windows/keyboard-navigation combinations that would make the UI unusable are rejected.
- Rebindings persist in state, immediately dispatch to the intended action, survive restart, and can be reset to defaults.
- Self-test must exercise registry completeness, unique defaults, rebind/get/dispatch for every action, conflict rejection, unsafe-key rejection, and reset-to-default behavior.

## Core functional regression matrix

Keep explicit regression coverage for:

- five independent decks;
- move current entry directly to any deck;
- switching active deck;
- shuffled-bag presentation with no repeats until the active deck is exhausted;
- previous/forward session navigation without resurrecting entries moved out of the active deck;
- empty-deck behavior;
- English side shown first and Ukrainian hidden until requested;
- deterministic repeat-word and reveal-translation UI Automation notifications;
- state save, atomic replacement, backup, and recovery;
- stale/invalid deck-state cleanup;
- strict TSV import validation and imported-dictionary persistence;
- keyboard-only operation and logical focus order;
- accessible names/descriptions for interactive controls;
- build-output self-test and published-EXE self-test.

## Development backlog after blockers

Prioritize additions that improve study flow without weakening accessibility or data integrity. Candidate improvements, in order:

1. Undo the last accidental deck move.
2. Export/import WordDeck progress and settings as a portable backup.
3. Clear/reset a selected deck or dictionary progress with an explicit confirmation.
4. Accessible session summary: cards seen, moved, and remaining in the active deck.
5. Search/find a word without changing its deck assignment.
6. Optional spelling mode that reads or exposes a word character by character using native accessible text, without adding cloud dependencies.
7. Better dictionary-management UI for multiple imported language packs.

Do not add accounts, telemetry, advertising, cloud synchronization, or unnecessary web/runtime dependencies.

## User-facing release rule

Do not send build files or download links proactively. Keep working and committing on the branch. Surface a user-facing update only for a blocker that requires user input or when the user explicitly asks for status/testing material.
