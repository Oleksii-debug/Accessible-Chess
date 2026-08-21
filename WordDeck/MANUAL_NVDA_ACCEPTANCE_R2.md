# WordDeck — manual NVDA acceptance — Round 2

Status: PENDING HUMAN TEST. This document is a checklist, not evidence of a manual NVDA PASS.

Run this only against the integrated Windows release that contains the Round-2 accessibility fixes. Use Windows 11, the user's normal NVDA configuration, and keyboard only.

## 1. Startup

1. Start `WordDeck.exe` without touching the mouse.
2. Confirm NVDA identifies the application and the current English word.
3. Press `Tab` and `Shift+Tab` through Dictionary, Study scope, Deck, Current English word and Ukrainian translation.
4. Confirm every control has an understandable name and focus order is stable.

## 2. Real-user regression: translation arrows must never change cards

1. Put focus on `Current English word`.
2. Note the word.
3. Press the current shortcut for Reveal translation (default `Ctrl+T`).
4. Confirm the Ukrainian translation is shown and focus moves to it.
5. While focus stays in the translation, press each of: `Up`, `Down`, `Left`, `Right`, `Home`, `End`, `Page Up`, `Page Down`.
6. Confirm the English card never changes, translation remains the same card, and NVDA can read/navigate the translation text.
7. Return to `Current English word`. Confirm `Down` now moves to the next Recall card and `Up` returns to the previous actually shown card.
8. Go back with `Up`, then use `Down`; confirm forward history is followed before a new shuffled card is drawn.

PASS criterion: unmodified Up/Down are fast Recall keys only on `Current English word`.

## 3. Real-user regression: Dictionary / Study scope / Deck selectors

For each selector — `Dictionary`, `Recall study scope`, `Active Recall deck`:

1. Reach it with `Tab`.
2. Without pressing `Enter`, press `Up` or `Down`.
3. Confirm the selected value changes when another option exists.
4. Confirm focus remains on the same selector after the change.
5. Press `Up`/`Down` several more times. Confirm each change is announced naturally by NVDA and focus does not jump to the English word.
6. Press `Tab` once and confirm movement continues from the selector rather than from a silently moved focus location.

For `Study scope` and `Deck`, repeat at least 10 consecutive arrow changes. For Dictionary, if only one dictionary is installed, confirm the key does not move focus away or require `Enter`.

## 4. 100-cycle focus stability stress

On `Recall study scope`, alternate `Up` and `Down` 100 times. Confirm:

- focus never jumps to Current English word;
- no Enter is required between changes;
- NVDA continues announcing the selector and selected value;
- WordDeck does not hang or stop responding.

Repeat at least 30 alternating changes on `Active Recall deck`.

## 5. Recall essential keyboard paths

Verify keyboard-only operation for:

- next / true previous / forward history;
- reveal translation without advancing;
- repeat English word;
- British offline pronunciation;
- automatic pronunciation toggle;
- switch core decks;
- move current word between decks;
- undo last move;
- save progress;
- hide current word, cancel and confirm paths;
- restore one hidden word and restore all;
- export profile, cancel and successful save paths;
- import profile cancel/validation path;
- reset learning data cancel path;
- `F1` help;
- shortcut settings.

Confirm modal dialogs return focus to a meaningful control and all confirmations can be completed or cancelled without a mouse.

## 6. F1 and shortcut truth

1. Open `F1`.
2. Confirm help states that fast Up/Down applies only on Current English word.
3. Confirm help states that translation navigation arrows remain inside the translation and do not change cards.
4. Confirm Recall, Spelling, Adaptive Coach and Sentence commands are present.
5. Confirm `Spelling: close trainer — standard Windows Alt+F4` is present.
6. Change one safe shortcut in shortcut settings, close settings, reopen `F1`, and confirm the displayed binding changed immediately.
7. Restart WordDeck and confirm the custom binding persists.
8. Restore the default if desired.

## 7. Shortcut conflict and unsafe-key behavior

1. Try assigning a standard typing/navigation chord such as unmodified `A`, `Left`, or `Home`; confirm WordDeck rejects it.
2. Try `Ctrl+C`; confirm it is rejected as a standard text-editing chord.
3. Confirm `Ctrl+Alt+Delete` cannot be assigned.
4. Select the fixed Spelling Alt+F4 row; confirm WordDeck explains that it is a standard Windows command and does not allow rebinding or clearing it.

## 8. Spelling

1. Open Spelling from the keyboard (default `Ctrl+Shift+S`).
2. Confirm initial focus is useful for entering the English answer when an exercise is available.
3. Type a wrong answer; confirm the word does not advance and focus remains useful.
4. Type the correct answer; confirm advancement and usable focus.
5. Test show answer, repeat Ukrainian prompt, pronunciation hint, Coach toggle, Coach undo and spelling deck operations.
6. Reach `Active spelling deck` with `Tab`, press `Up`/`Down` without Enter, and confirm focus stays on the selector.
7. Press `Alt+F4`. Confirm Spelling closes safely and returns to WordDeck; reopen it and confirm its saved state is intact.

## 9. Sentence Spelling

1. Open Sentence Spelling from the keyboard (default `Ctrl+Shift+E`).
2. Confirm Sentence pack, spelling-deck scope and target-count selectors are keyboard reachable and named.
3. On each selector, use `Up`/`Down` without Enter; confirm focus stays on the selector.
4. Confirm the answer field is keyboard reachable and normal text editing keys are not stolen by Recall or Spelling shortcuts.
5. Test show answer, repeat prompt and SentencePack import cancel path.
6. Close with `Alt+F4` and confirm focus returns to WordDeck.

If no SentencePack is installed, confirm the missing-pack state is announced textually and the form remains operable.

## 10. Final result to report

Report each failed step with: window/mode, focused control, key pressed, what NVDA said, what actually happened, and whether focus moved unexpectedly.

Only after every required item passes may a human reviewer state `MANUAL NVDA PASS`. Automated self-tests or Windows UI Automation must never be reported as that manual pass.
