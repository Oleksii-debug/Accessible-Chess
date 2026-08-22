# WordDeck Round 3 — keyboard/accessibility engineering matrix

This matrix records the engineering contract. Automated rows still require the exact Windows gate; physical NVDA acceptance is tracked separately in `MANUAL_NVDA_ACCEPTANCE_R3.md`.

| Surface | Native control / route | Required keyboard/focus contract | R3 protection |
|---|---|---|---|
| Main English word | read-only multiline TextBox | unmodified Down = next; Up = true previous only while this surface is focused | canonical focus policy + self-test + UIA |
| Ukrainian translation | read-only multiline TextBox | Ctrl+T focuses translation; all normal text/navigation arrows remain native; card does not change | canonical focus policy + self-test + UIA |
| Dictionary | ComboBox DropDownList | Tab focus; Up/Down changes selection without Enter; selector retains focus | canonical focus-aware selector path + UIA |
| Recall scope | ComboBox DropDownList | same native selector contract through repeated changes | canonical focus-aware selector path + 100-cycle UIA |
| Recall deck | ComboBox DropDownList | same native selector contract | canonical focus-aware selector path + UIA |
| Main menus | MenuStrip / ToolStripMenuItem | menu arrows remain native and never become Recall navigation | UIA card-invariant check |
| Shortcut settings | ListView + Buttons | initial focus on action list; arrows native; Tab/Shift+Tab reaches controls; status text readable | R3 form hardening + UIA |
| Shortcut capture | read-only TextBox + Cancel | capture only safe combinations; Esc cancels; native/system/text-edit keys protected | shared registry self-test |
| Shared shortcut registry | application state + definitions | one visible source of truth; duplicate imported bindings fail closed; mode actions do not shadow other modes | R3 context policy + self-test |
| Spelling deck | ComboBox DropDownList | Up/Down changes deck/exercise but keeps focus in selector | R3 focus-aware Spelling path + UIA |
| Spelling answer | TextBox | native text navigation/editing; foreign Recall/Sentence actions are not consumed | context dispatch + UIA |
| Spelling status | Label | text feedback without stealing answer/selector focus | native label/announcer + manual NVDA |
| Spelling close | native window command | Alt+F4 closes/saves; visible in help/settings; not rebindable or intercepted | shared registry self-test + UIA |
| Sentence pack | ComboBox DropDownList | native selector; changing pack does not steal focus when selector initiated the change | R3 focus-aware Sentence path + manual/UIA where values exist |
| Sentence spelling deck | ComboBox DropDownList | native selector; exercise refresh does not force answer focus | R3 focus-aware Sentence path + UIA |
| Sentence target count | ComboBox DropDownList | native Up/Down; focus retained | R3 focus-aware Sentence path + UIA |
| Sentence answer | multiline TextBox | normal text navigation/editing; foreign mode shortcuts are not consumed | context dispatch + UIA |
| F1 help | read-only multiline TextBox | keyboard-first contract and actual current bindings, including Alt+F4 truth | shared definitions + UIA text check |
| Hide/restore | menu/dialog native controls | reversible user overlay; keyboard route and readable confirmations/status | existing user-data tests + manual NVDA checklist |
| Profile export/import | menu + file dialogs | keyboard route; validation/backup/fail-closed behavior preserved; no mouse-only path | existing canonical regression + manual NVDA checklist |
| Reset | menu + confirmation | explicit confirmation + recovery backup; keyboard cancellable | existing canonical regression + manual NVDA checklist |
| Add/move/rename/delete decks | native dialogs/lists/buttons | keyboard reachable; no visual-only state; safe cancel | existing controls + manual NVDA checklist |

## Mode isolation rule

When a form handles app shortcuts, it only dispatches actions owned by its semantic context. Recall does not consume Spelling/Sentence actions, Spelling does not consume Recall/Sentence actions, and Sentence does not consume Recall/Spelling actions. Unhandled keys return to native WinForms processing.

## Focus rule

A state refresh may update the current exercise without taking focus away from the selector/input that initiated the change. Deliberate exercise navigation may focus the intended word/answer surface. Status announcements must not silently move keyboard focus.

## Evidence status

Source-level protections and self-tests are present in the R3 worker branch. Final machine status must be filled from the exact-tip Windows GitHub Actions run; physical NVDA status remains human-only.

The automated PR evidence run uses the isolated DEV4-only base branch `worddeck-worker-4-accessibility-r3-ci-base`. That branch is only a CI transport required because canonical advanced concurrently beyond the fixed Round-3 base; it is not a product integration target and must never be merged into canonical.
