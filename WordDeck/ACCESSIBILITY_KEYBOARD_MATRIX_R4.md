# WordDeck Round 4 keyboard and focus acceptance matrix

This matrix is a release gate for keyboard-only use. It does not claim a physical NVDA pass.

## Recall

- Current English word: unmodified Down advances to the next card; unmodified Up returns to the previous actually shown eligible card.
- Ukrainian translation: Up/Down/Left/Right/Home/End/PageUp/PageDown remain native text-navigation keys and must not change the card.
- Dictionary, Recall study scope and Active Recall deck selectors: native Up/Down selection works without Enter; focus remains in the selector after the value changes and UI Automation exposes the selected value.
- Repeated selector cycles must not bounce focus back to Current English word.
- File/menu surfaces: arrow keys navigate menus and must not change cards.
- Ctrl+Left/Ctrl+Right compatibility navigation remains separate from native unmodified text arrows.
- Tab traversal must reach dictionary, scope, deck, English word, translation and menu/commands without mouse-only gaps.

## Spelling

- Spelling study scope and Active spelling deck selectors: native Up/Down selection changes the value while retaining selector focus.
- English answer field: arrow/Home/End/Page keys remain native editing/navigation keys.
- Recall and Sentence shortcuts must not be consumed by the Spelling form.
- Alt+F4 is a fixed standard Windows close command and must not be rebound or swallowed.
- Ctrl+Shift+Delete remains the safe user-spelling-deck delete command; Ctrl+Alt+Delete is reserved and rejected.
- Tab traversal reaches selectors, prompt, answer, status and menus.

## Sentence Spelling

- Sentence pack, spelling-deck scope and target-count selectors retain focus during native keyboard selection.
- English answer field retains native arrow/Home/End/Page behavior.
- Recall and Spelling shortcuts must not be consumed by the Sentence form.
- Alt+F4 closes the trainer through normal WinForms behavior.
- Tab traversal reaches all selectors, prompt, answer, status/mode information and menus.

## Shortcut registry, settings and F1

- Static Recall, Spelling and Sentence actions come from one ShortcutManager registry even when the main Recall window does not have live Spelling deck context.
- Main-window dispatch is Recall-context only; Spelling/Sentence entry-point keys fall through to their WinForms menu commands instead of being swallowed.
- Dynamic Spelling deck bindings are preserved by Recall-only refresh and are removed only when a manager with explicit Spelling deck context proves them orphaned.
- F1 must expose current static Recall/Spelling/Sentence bindings and the current Recall Up/Down focus rule.
- Shortcut ListView is the initial focus target.
- Enter opens capture for the selected action; Esc cancels capture and returns safely.
- Tab/Escape/Enter, Alt+F4, Ctrl+Alt+Delete and unmodified text/navigation arrows are not assignable to arbitrary actions.
- Imported duplicate bindings fail closed rather than dispatching whichever action happens to appear first.

## Dialogs, profiles and recovery

- Open/Save/Import dialogs are standard Windows dialogs and remain keyboard operated.
- Cancelling legacy Recall-only profile Export/Import returns focus to Current English word without changing the current card.
- Cancelling complete Recall+Spelling+Sentence profile Export/Import returns safely and does not mutate live state.
- Reset learning data requires explicit confirmation; default/cancel path must not reset state.
- Risky import/reset paths preserve backup/recovery guarantees.
- User progress remains under the Windows user profile, not in the public application folder.

## Repeated mode switching

- Repeated Recall -> Spelling -> Recall and Recall -> Sentence -> Recall cycles close with Alt+F4 and return to a usable main window.
- Mode switching must not leave hidden modal windows, corrupt shortcut context or move personal state into the application directory.

## Evidence levels

1. Deterministic source/self-test: required.
2. Windows UI Automation execution against the exact published EXE: required; a skipped UIA test is not a pass.
3. Physical NVDA acceptance on Windows 11: human-only gate; never inferred from automation.
