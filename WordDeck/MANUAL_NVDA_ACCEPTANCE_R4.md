# WordDeck Round 4 manual NVDA acceptance checklist

This checklist must be executed by a human on a physical Windows 11 computer with NVDA. Automation must not be reported as a manual NVDA PASS.

Record Windows version, NVDA version and exact release-build identity before testing. A single P0 keyboard/focus failure blocks manual acceptance.

1. Start the exact release build without administrator rights. Confirm NVDA announces the WordDeck window and the current English word.
2. Tab through Dictionary, Recall study scope, Active Recall deck, Current English word and Ukrainian translation. Confirm every control has a useful announced name and focus order is predictable.
3. On Current English word press Down several times, then Up several times. Confirm Down advances and Up returns through cards actually shown.
4. Reveal translation with Ctrl+T. While focus is in Ukrainian translation, use Up/Down/Left/Right/Home/End/PageUp/PageDown. Confirm NVDA/text navigation works and the Recall card does not change.
5. Focus Dictionary, Recall study scope and Active Recall deck. Use Up/Down repeatedly without Enter. Confirm the selected value is announced and focus stays in that selector after many changes.
6. Open File and other menus by keyboard. Navigate with arrows. Confirm card selection does not change.
7. Press F1. Confirm help accurately describes the current shortcuts, includes the Spelling and Sentence Spelling entry points, and states that unmodified Recall Up/Down apply only on Current English word. Close help with Alt+F4.
8. Open shortcut settings with Ctrl+K. Confirm Shortcut actions receives focus. Press Enter to open capture, then Esc to cancel. Confirm focus returns safely. Confirm attempts to bind Alt+F4, Ctrl+Alt+Delete or unmodified Left/Right fail with readable feedback.
9. Open Spelling with its configured shortcut. Use Up/Down in Spelling study scope and Active spelling deck. Confirm value changes are announced and selector focus remains. In the answer field verify arrows/Home/End/PageUp/PageDown behave normally.
10. In Spelling press a Recall-only shortcut such as Ctrl+T and a Sentence-only shortcut such as Ctrl+Alt+H. Confirm they do not trigger hidden Spelling actions or unexpectedly move focus/content.
11. Close Spelling with Alt+F4. Repeat open/close at least three times. Confirm it closes safely and the main WordDeck window remains usable.
12. Open Sentence Spelling. Test Sentence pack, spelling-deck scope and target-count selectors with Up/Down and verify focus retention. Verify answer-field arrows remain native. Close with Alt+F4 and repeat the mode-switch cycle.
13. Open legacy Recall-profile Export and Import dialogs by keyboard, cancel each, and confirm the current card is unchanged and focus returns to Current English word.
14. Open complete Recall+Spelling+Sentence profile Export and Import from Tools using keyboard only. Cancel each once before doing any destructive test; confirm state is unchanged.
15. Export a complete personal profile to a disposable test path, then import it back. Confirm Recall progress/hidden words, Spelling state and Sentence state remain usable.
16. Open Reset Recall learning data. Confirm No/cancel is the safe default and leaves state unchanged. Perform an actual reset only with a disposable test profile; verify backup/recovery messaging is understandable and canonical dictionary/audio assets remain present.
17. Restart WordDeck. Confirm active scopes/decks, shortcuts and personal learning state survive restart.
18. If a user-created Spelling deck with a custom shortcut exists, visit Recall/help/settings and return to Spelling. Confirm the custom dynamic Spelling shortcut has not disappeared.
19. Verify there are no mouse-only commands required to complete Recall, Spelling, Sentence, shortcut configuration, profile export/import or safe recovery.

For every failed or confusing item record the exact keystrokes, focused control name, NVDA announcement and whether user data changed. Do not convert an automated UIA result into a manual NVDA PASS.
