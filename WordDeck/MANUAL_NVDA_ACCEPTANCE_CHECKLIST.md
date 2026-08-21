# WordDeck manual NVDA acceptance checklist

This checklist is intentionally separate from automated tests. A green build, self-test or UI Automation run is not a manual NVDA PASS. Record PASS only after a person actually performs these checks on the target Windows 11 computer with NVDA running.

## Test record

- WordDeck build/version:
- Windows 11 version:
- NVDA version:
- Tester:
- Date/time:
- Result: PENDING / PASS / FAIL
- Notes or failures:

## 1. Startup and focus

- [ ] Start WordDeck without using the mouse.
- [ ] NVDA announces the current English word after startup.
- [ ] Keyboard focus is on the current English word, not on a decorative label or hidden control.
- [ ] Tab reaches Dictionary, Recall study scope, Recall deck, current word and translation in a predictable order.
- [ ] Shift+Tab reverses that route predictably.
- [ ] Combo boxes keep normal Up/Down navigation when they have focus.
- [ ] Menus keep normal arrow-key navigation.

## 2. Recall navigation contract

Use the active shortcuts reported by F1 rather than assuming defaults.

- [ ] Next-card action shows a different eligible card when possible.
- [ ] Previous-card action returns to the actual previously shown card.
- [ ] After going back, next-card first moves forward through the already shown history.
- [ ] After the newest history card, next-card resumes the shuffled sequence.
- [ ] Left and Right work as normal caret/text navigation in text surfaces.
- [ ] Ctrl+Right remains the fixed compatibility next-card command.
- [ ] Ctrl+Left remains the fixed compatibility previous-card command.
- [ ] Reveal translation announces the Ukrainian translation and does not advance the card.
- [ ] Repeat English announces the current English word.
- [ ] Save progress produces a clear status message.
- [ ] Undo after moving a card between Recall decks returns the card correctly and announces the result.

## 3. Recall scopes and decks

- [ ] All Oxford 5000, A1, A2, B1, B2 and C1 are reachable by keyboard.
- [ ] No C2 scope is offered.
- [ ] Switching scope announces the new scope and keeps focus usable.
- [ ] Switching Recall deck announces the destination deck.
- [ ] Moving a word to another deck announces the move.
- [ ] Creating a user deck is keyboard-only; the name field receives focus; Enter confirms; Escape cancels.
- [ ] Renaming a deck preserves a usable focus route.
- [ ] Deleting a non-empty user deck requires a destination and can be cancelled with Escape.
- [ ] Destination-deck dialog exposes a usable ComboBox and clear OK/Cancel controls.

## 4. Hide, restore, profile and reset

- [ ] Hide current word clearly states that the word is hidden from study, not deleted from the dictionary.
- [ ] Hidden word no longer appears in normal Recall navigation.
- [ ] Restore one hidden word is completely keyboard-operable.
- [ ] Restore all hidden words requires confirmation and announces the result.
- [ ] Export personal profile is keyboard-operable and the save dialog is usable with NVDA.
- [ ] Import personal profile is keyboard-operable and reports invalid input as readable text instead of silently replacing data.
- [ ] Reset Recall learning data clearly warns before the destructive action.
- [ ] Canceling reset leaves learning data unchanged.
- [ ] Confirmed reset reports that a recovery backup was created.

## 5. British pronunciation

- [ ] Play-pronunciation action plays the local British audio when a file exists.
- [ ] Auto-pronunciation can be toggled from the keyboard and the state change is announced.
- [ ] When audio is unavailable, WordDeck reports a readable status and remains usable.
- [ ] Screen-reader word announcement remains available when audio is unavailable or auto-pronunciation is off.

## 6. Shortcut settings and F1 truth

- [ ] Open shortcut settings entirely from the keyboard.
- [ ] Focus starts on the action list.
- [ ] NVDA reads each action and its current shortcut clearly enough to identify both.
- [ ] Enter on a selected action opens shortcut capture.
- [ ] Escape cancels capture without changing the binding.
- [ ] Rebinding an action takes effect immediately after the dialog closes.
- [ ] A shortcut remains changed after restarting WordDeck.
- [ ] Clearing an action causes F1 to report it as Unassigned.
- [ ] Attempting a conflicting shortcut is rejected with a readable explanation.
- [ ] Attempting Ctrl+Alt+Delete, Alt+F4, Alt+Space, plain typing keys, plain Left/Right, or standard Ctrl+C/Ctrl+X/Ctrl+V is rejected.
- [ ] F1 opens with the currently configured Help binding.
- [ ] F1 includes Recall, Spelling, Adaptive Coach, Sentence Spelling, profile/hide/reset and dynamic deck actions that currently exist.
- [ ] F1 reports actual current bindings rather than old defaults after a rebind.
- [ ] F1 explicitly says Unassigned for actions without a key binding.
- [ ] Closing F1 returns focus to the current English word.

## 7. Spelling trainer

- [ ] Open Spelling without the mouse.
- [ ] The spelling answer field receives focus after a card loads.
- [ ] NVDA announces the Ukrainian prompt.
- [ ] Standard typing and caret movement in the answer field are not swallowed by Recall shortcuts.
- [ ] Left/Right/Home/End and normal editing work in the answer field.
- [ ] Wrong spelling produces a clear spoken/readable status and does not advance.
- [ ] Correct spelling produces a clear status and advances.
- [ ] Show answer announces the required English spelling but still requires typing it.
- [ ] Repeat Ukrainian prompt announces the prompt and returns focus to the answer field.
- [ ] British pronunciation hint works or reports a readable missing-audio status.
- [ ] Toggle Adaptive Coach announces enabled/disabled state.
- [ ] Undo last Coach move reports success or an explicit reason when undo is unavailable.
- [ ] Core spelling decks switch by their configured bindings.
- [ ] Move-to-spelling-deck bindings move the current word and announce the destination.
- [ ] Create, rename, reorder and delete user spelling decks are fully keyboard-operable.
- [ ] Delete spelling deck uses its configured binding; the default is Ctrl+Shift+Delete and does not conflict with Recall hide.
- [ ] An empty spelling deck leaves focus in a usable control and announces what to do next.

## 8. Sentence Spelling

- [ ] Open Sentence Spelling without the mouse.
- [ ] SentencePack selector, spelling-deck scope and target-count selector are reachable with Tab.
- [ ] If no SentencePack is installed, the status explains how to import one.
- [ ] SentencePack import dialog is keyboard-operable.
- [ ] With a pack installed, NVDA announces the Ukrainian sentence prompt.
- [ ] One-target and two-target modes can be selected without the mouse.
- [ ] The answer field is reachable and normal editing keys work.
- [ ] Wrong answer gives readable feedback and does not advance.
- [ ] Correct answer gives readable feedback and advances.
- [ ] Show-answer and repeat-Ukrainian actions work with the currently configured bindings.

## 9. Modal focus and no-mouse audit

- [ ] Every confirmation dialog has a clear default/cancel route using Enter/Escape where appropriate.
- [ ] After closing a modal dialog, focus returns to a sensible WordDeck control.
- [ ] No essential Recall, Spelling, Coach, Sentence, profile, hide/restore, reset or shortcut function requires pointer coordinates or mouse-only interaction.
- [ ] Status/error messages are text, are understandable with NVDA and do not rely only on color or visual placement.

## 10. Final acceptance

- [ ] Repeat the most important Recall path after restarting WordDeck to verify persisted focus/state/shortcuts.
- [ ] Record any NVDA-specific speech/focus anomaly with exact keystrokes and the control where it occurred.
- [ ] Mark PASS only if all essential checks above pass or any intentional exception is documented and accepted.

Current engineering rule: until this checklist is physically executed by the user/tester with NVDA, manual NVDA status remains PENDING.
