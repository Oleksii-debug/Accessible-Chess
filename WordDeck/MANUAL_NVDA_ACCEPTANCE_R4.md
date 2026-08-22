# WordDeck Round 4 manual NVDA acceptance checklist

This checklist must be executed by a human on a physical Windows 11 computer with NVDA. Automation must not be reported as a manual NVDA PASS.

1. Start the release build without administrator rights. Confirm NVDA announces the WordDeck window and the current English word.
2. Tab through Dictionary, Recall study scope, Active Recall deck, Current English word and Ukrainian translation. Confirm every control has a useful announced name and focus order is predictable.
3. On Current English word press Down several times, then Up several times. Confirm Down advances and Up returns through cards actually shown.
4. Reveal translation with Ctrl+T. While focus is in Ukrainian translation, use Up/Down/Left/Right/Home/End. Confirm NVDA/text navigation works and the Recall card does not change.
5. Focus Dictionary, Recall study scope and Active Recall deck. Use Up/Down repeatedly without Enter. Confirm the selected value is announced and focus stays in that selector.
6. Open File and other menus by keyboard. Navigate with arrows. Confirm card selection does not change.
7. Press F1. Confirm help accurately describes the current shortcuts and the rule that unmodified Recall Up/Down only apply on the English-word surface. Close help with Alt+F4.
8. Open shortcut settings with Ctrl+K. Confirm the action list receives focus; Enter opens capture; Esc cancels. Confirm attempts to bind Alt+F4, Ctrl+Alt+Delete or unmodified Left/Right fail with readable feedback.
9. Open Spelling. Use Up/Down in Spelling study scope and Active spelling deck. Confirm value changes are announced and selector focus remains. In the answer field verify arrows/Home/End edit normally.
10. In Spelling press a Recall-only shortcut such as Ctrl+T and a Sentence-only shortcut such as Ctrl+Alt+H. Confirm they do not trigger hidden Spelling actions or unexpectedly move focus/content.
11. Close Spelling with Alt+F4. Confirm it closes safely with no prompt/state corruption.
12. Open Sentence Spelling. Test Sentence pack, spelling-deck scope and target-count selectors with Up/Down and verify focus retention. Verify answer-field arrows remain native.
13. Export the complete personal profile, then import it back. Confirm progress, hidden words, Spelling state and Sentence state remain usable.
14. Perform a safe reset only with a disposable test profile. Confirm backup/recovery messaging is understandable and no public dictionary/audio assets are deleted.
15. Restart WordDeck. Confirm active scopes/decks and personal learning state survive the restart.

Record Windows version, NVDA version, release build identity, result for each item, and any exact NVDA announcement that is confusing. A single P0 keyboard/focus failure blocks manual acceptance.
