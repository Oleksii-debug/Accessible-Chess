# WordDeck Round 4b — accessibility/release acceptance matrix

This is a machine + human release matrix. It does not turn UI Automation into a physical NVDA PASS.

## Recall P0
- Current English word: unmodified Down = next; unmodified Up = previous actually shown eligible card.
- Ukrainian translation: Up/Down/Left/Right/Home/End/PageUp/PageDown remain native text navigation and never change the Recall card.
- Dictionary / Recall study scope / Active Recall deck: native Up/Down works without Enter and focus remains on the selector after refresh.
- Menus keep native arrow navigation; menu arrows never change a Recall card.

## Shortcut truth
- Ctrl+K opens Keyboard shortcuts; the action list is the initial useful focus target.
- Enter opens shortcut capture; Esc cancels capture without closing the settings window.
- Alt+F4, Ctrl+Alt+Delete and unmodified text/navigation arrows remain protected from arbitrary rebinding.
- Context-aware dispatch prevents Recall shortcuts from becoming hidden Spelling/Sentence actions and vice versa.
- F1/help must derive from current binding truth and explicitly document the Recall arrow scope and safe Alt+F4 behavior.

## Spelling
- Scope/deck selectors retain focus during native keyboard changes.
- Answer input retains native text-navigation keys.
- Wrong/correct/show-answer/hint/Coach outcomes remain keyboard reachable with readable status.
- Alt+F4 closes safely through normal state lifecycle.

## Sentence
- Sentence pack, spelling deck/scope and target-count selectors retain focus during keyboard changes.
- Answer input keeps native arrows/Home/End/Page keys.
- Import/error/diagnostic/show/repeat surfaces must expose readable text and keyboard actions.
- Absence of a production SentencePack must not crash normal startup.

## Profile / recovery
- Export and import dialogs are standard keyboard-operable Windows dialogs.
- Reset requires explicit confirmation and can be cancelled without mutation.
- Deterministic regression covers unified Recall+Spelling+Sentence profile, incompatible-corpus rejection, backup/recovery and state continuity.
- Personal state remains under %LOCALAPPDATA%\WordDeck and outside public packages.

## Windows release gate
Required on exact worker tip:
1. source-read-only branch/head binding;
2. secrets/private-state/personal-path scan;
3. offline/no-admin contract;
4. restore + Release warnings-as-errors;
5. complete deterministic --self-test;
6. self-contained win-x64 publish;
7. published WordDeck.exe --self-test from a path containing spaces and Cyrillic;
8. public artifact cleanliness;
9. ACTUAL Windows UI Automation execution covering Recall P0, selectors, menus, F1, shortcut settings, profile/import/reset dialogs, Spelling and Sentence surfaces;
10. evidence artifact tied to exact SHA.

## Evidence levels
- Deterministic self-test PASS: code/state contract evidence.
- Windows UIA PASS: actual hosted Windows GUI automation evidence.
- Physical NVDA PASS: human-only on the exact final build; never inferred from automation.
