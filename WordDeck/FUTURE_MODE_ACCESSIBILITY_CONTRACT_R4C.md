# WordDeck — future-mode accessibility contract (R4c)

Purpose: define non-invasive acceptance requirements for already approved post-Foundation modes. This file does **not** activate or implement Grammar, Dictation, Story, Reading, Book Import, Word Families or the Narrative Course during Round 4.

## Global contract
- Keyboard-only completion of every essential action; no coordinate, hover or mouse-only dependency.
- Prefer native/semantic controls with meaningful accessible names, roles, values and states.
- Logical Tab/Shift+Tab order and predictable focus return after dialogs, validation and mode changes.
- Native text editing/navigation keys stay native inside text inputs.
- Passive status/progress updates never steal the user's working focus.
- Errors, validation, progress and completion state have concise textual equivalents.
- High contrast, scaling and reduced motion must not hide state or focus.
- Future visual/WebView/HTML shells require semantic HTML first, ARIA only where needed, and exact NVDA/keyboard parity before replacing a working native screen.

## Grammar Coach
- Prompt/instruction, target skill, editable production field, check action, feedback and next action must have explicit accessible identities.
- Arrow/Home/End/Ctrl+Arrow in production fields remain native editing.
- Validation feedback must identify the relevant field and error text without forcing focus away while the user is correcting it.
- Multiple-choice grammar uses native list/radio semantics; no custom visual-only selection.
- Correct/incorrect state may use colour visually but always has a textual/screen-reader equivalent.

## Dictation / listening
- Play/replay/pause controls are real buttons with stable shortcuts that do not override native text editing.
- Answer field is a native text input; audio state, unavailable audio and completion status are announced textually.
- No timing-only interaction: users must be able to request replay and inspect feedback without relying on visual waveform/progress.
- Volume/audio failure never traps focus or destroys the current exercise.

## Story / Narrative Course
- Story structure exposes meaningful headings/sections and a stable reading order.
- Choices are native buttons/list items with textual labels; visual cards are not the only interaction surface.
- Returning from an exercise restores a useful story position/focus rather than restarting at the top.
- Progress, locked/unlocked state and mastery requirements are available as text.
- Optional images require useful alt/hint semantics and must not unintentionally reveal a hidden answer.

## Reading
- Document/book title, chapter/section headings and reading content use semantic navigation.
- Screen-reader reading must not be interrupted by unrelated live-region/status chatter.
- Vocabulary actions reachable from reading text must preserve reading position and provide a keyboard path back.
- Search/go-to/chapter navigation must not depend on visual pagination.

## Local Book/Text Import
- Import is keyboard reachable using standard file dialogs or accessible equivalent.
- Selected file, detected type/encoding, import scope, warnings, privacy/local-processing status and errors are exposed as text.
- Cancel performs no partial destructive mutation.
- Unsupported/corrupt/oversized input fails safely with readable diagnostics.
- Local books/texts are private by default; future network services must not upload them without an explicit product decision and informed user action.

## Cross-mode mastery / router
- Mode recommendations and mastery reasons need textual explanations; no progress information solely in charts/colour.
- Switching modes preserves or deliberately moves focus to a documented start target.
- Global shortcuts must be context-aware so commands from one mode do not fire inside another mode's text/select/menu controls.
- Offline progress remains canonical unless a later explicitly approved sync policy changes that rule.

## Acceptance gate for a future mode
A future mode is not accessibility-complete until: deterministic keyboard/focus tests pass, exact Windows UIA executes against the release-form artifact where applicable, a human NVDA checklist is run on the exact candidate, and every remaining human-only item is explicitly recorded. Automated UIA must never be reported as physical NVDA PASS.
