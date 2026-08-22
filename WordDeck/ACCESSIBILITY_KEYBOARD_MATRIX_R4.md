# WordDeck Round 4 keyboard and focus acceptance matrix

This matrix is a release gate for keyboard-only use. It does not claim a physical NVDA pass.

## Recall

- Current English word: unmodified Down advances to the next card; unmodified Up returns to the previous actually shown card.
- Ukrainian translation: Up/Down/Left/Right/Home/End/PageUp/PageDown remain native text-navigation keys and must not change the card.
- Dictionary, Recall study scope and Active Recall deck selectors: native Up/Down selection works without Enter; focus remains in the selector after the value changes.
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

## Shortcut settings

- ListView is the initial focus target.
- Enter opens capture for the selected action; Esc cancels capture.
- Tab/Escape/Enter, Alt+F4, Ctrl+Alt+Delete and unmodified text/navigation arrows are not assignable to arbitrary actions.
- Imported duplicate bindings fail closed rather than dispatching whichever action appears first.

## Dialogs and profile/recovery

- Open/Save/Import dialogs are standard Windows dialogs and remain keyboard operated.
- Destructive/reset paths require explicit confirmation and preserve backup/recovery guarantees.
- User progress remains under the Windows user profile, not in the public application folder.

## Evidence levels

1. Deterministic source/self-test: required.
2. Windows UI Automation execution: required where the hosted provider exposes the WinForms client tree.
3. Physical NVDA acceptance: human-only gate; never inferred from automation.
