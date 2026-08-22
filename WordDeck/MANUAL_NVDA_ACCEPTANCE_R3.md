# WordDeck Round 3 — manual NVDA acceptance

Status: **PENDING HUMAN TEST**. Automated build/self-test/UI Automation does not equal a physical NVDA PASS.

Record before testing: exact WordDeck build/branch identifier, Windows version, NVDA version, and whether the profile is fresh or existing.

## 1. Recall — real-user P0 regression

1. Start WordDeck with NVDA. Confirm focus reaches `Current English word` and NVDA announces the word.
2. Press `Ctrl+T`. Confirm focus moves to `Ukrainian translation` and the translation is readable.
3. While translation is focused, press Up, Down, Left, Right, Home, End, Page Up and Page Down. Confirm the same Recall card remains active and focus stays in translation.
4. Return to `Current English word`. Down must show the next card. Up must return to the previous actually shown card.
5. Tab to `Dictionary`, `Recall study scope`, and `Active Recall deck`. For each selector, use Up/Down repeatedly without Enter. Confirm the selected value changes normally and focus stays in that selector so NVDA can announce the value.
6. Repeat scope changes at least 30 times and deck changes at least 20 times. Confirm there is no focus jump to the word card, double action, dead focus or card-history corruption.
7. Open the File menu and use arrow keys. Confirm menu arrows do not change Recall cards.

## 2. Shortcut truth and settings

1. Press F1. Confirm help states that fast Up/Down works only on the English word, translation/selectors use native arrows, and Spelling closes with Alt+F4.
2. Press `Ctrl+K`. Confirm initial focus is on `Shortcut actions`.
3. Navigate the shortcut list with arrows and Tab through Change, Clear, Reset and Close.
4. Confirm the list includes `Spelling: close trainer — standard Windows Alt+F4` and that attempts to change/clear that fixed Windows command are rejected with readable text feedback.
5. Rebind one safe non-essential action, close settings, reopen, and confirm the displayed binding persists. Restore the original binding afterward.

## 3. Spelling

1. Open Spelling from the keyboard.
2. Tab to `Active spelling deck`. Use Up/Down repeatedly. Confirm the exercise may update but focus remains in the deck selector and NVDA announces its selected value.
3. Tab to `Type English spelling answer`. Verify normal Left/Right/Home/End text navigation and editing. Arrow/navigation keys must not trigger Recall or Sentence actions.
4. Submit one wrong answer. Confirm the answer field remains usable and the exercise does not advance.
5. Use Show answer / Repeat prompt / pronunciation / Adaptive Coach routes from the keyboard.
6. Press Alt+F4. Confirm Spelling closes safely and the main WordDeck window returns; reopen Spelling and confirm saved state is intact.

## 4. Sentence Spelling

1. Open Sentence Spelling from the keyboard.
2. If no SentencePack is installed, confirm the no-pack message is readable and the rest of the window remains keyboard navigable.
3. Use Up/Down in `Sentence pack` when values exist, `Sentence training spelling deck`, and `Number of target words per sentence`. Confirm focus remains in the selector after each change.
4. Tab to `Type the English sentence words`. Verify normal text navigation/editing; arrows must not invoke Recall/Spelling shortcuts.
5. Verify Show answer, Repeat prompt and SentencePack import routes can be reached without a mouse.
6. Close with Alt+F4 and confirm control returns safely to the main app.

## 5. User-data and dialogs

Using only keyboard navigation, open and cancel/complete as appropriate: hide word, restore hidden word, restore all, profile export, profile import, reset learning data, add words, deck chooser/name dialogs and error/confirmation dialogs. Confirm controls have readable names, focus is predictable, cancellation is possible, and no operation requires a mouse.

Do not intentionally replace valid personal state with a test profile unless a backup/export has been made first.

## 6. Result format

For every failure record: window/control, exact keys, expected behavior, actual behavior, whether focus moved, NVDA speech if relevant, and whether the same result repeats.

Only after this checklist is performed on the exact integrated/release build may a human report `MANUAL NVDA PASS`. Developer automation must never self-claim it.
