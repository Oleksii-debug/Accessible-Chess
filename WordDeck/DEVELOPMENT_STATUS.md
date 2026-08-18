# WordDeck development checkpoint

Last updated: 2026-08-18
Branch: `worddeck-bootstrap` only. Never develop WordDeck on `main`.

## Emergency Oxford 5000 milestone

### Oxford lexical data
- Embedded production dictionary remains the verified Oxford 3000 baseline: **3,308 lexical rows**, A1-B2. Do not claim Oxford 5000 complete yet.
- Oxford 5000 additions **0001-0100** were previously translated/reviewed.
- Source-backed second-pass verification is complete through **0140**: slices 0101-0120 and 0121-0140 are explicit `verified` OALD-reviewed rows.
- Staged extraction 0141-0200 already exists with official level/POS metadata and Ukrainian drafts, but remains `needs_second_pass`; it is not eligible for production embedding yet.
- Remaining authoritative extraction/QA after 0200 is incomplete. C1 must come only from Oxford 5000 additions. No Oxford C2 scope or invented C2 entries.
- Exact next data action: second-pass 0141-0200 in a large fail-closed slice, isolating ambiguous rows without blocking later extraction, then continue authoritative extraction beyond 0200.

### Recall Study Scope / Workspace
- Durable scope IDs are exactly: `all`, `a1`, `a2`, `b1`, `b2`, `c1`; display labels are `All Oxford 5000`, `A1`, `A2`, `B1`, `B2`, `C1`.
- Scope storage now persists independent **deck assignments, active deck, current card and remaining shuffle progress** for every dictionary/scope.
- Legacy Recall assignments/current card/active deck migrate losslessly into `All`; level scopes contain only exact CEFR rows and initialize eligible entries to core deck 1.
- Nested scope dictionaries are normalized after JSON reload with case-insensitive keys, invalid deck repair and invalid current-card repair. Existing `state.json` + recovery backup behavior remains intact.
- Main Recall UI now has a native WinForms **Study scope ComboBox** with keyboard/NVDA-accessible name and description. Switching scope restores that scope's active deck/current card/shuffle progress and announces scope + total.
- Current-scope counts are shown for all decks with a clear scope total.
- Existing `Ctrl+1..5` and `Alt+1..5` continue to switch/move among the shared five core decks, but now operate only inside the CURRENT scope.
- Stable rebindable actions `recall_scope_<scopeId>` exist for all six scopes and default to `Unassigned`.
- Custom pasted cards are deliberately restricted to `All Oxford 5000` so A1-C1 workspaces remain official CEFR subsets. Existing custom-deck definitions remain usable. Scope assignments are migrated safely if a user deck is deleted.
- Regression coverage is now wired into `--self-test`: legacy-to-All migration, exact CEFR filtering, independent assignments, independent active deck/current card/shuffle, JSON round-trip persistence, ineligible-entry rejection, all six dynamic scope actions, rebinding/conflict rejection and canonical shortcut formatting.
- **Verification state:** implementation is landed on `worddeck-bootstrap`; do not call the vertical slice user-testable until the grouped Windows build/self-test/published-EXE gate is green for the final scope head.
- Exact next scope action: inspect/fix the grouped Windows gate if needed, then do a final native-focus/NVDA-oriented code audit before producing any beta artifact.

### British offline audio
- Existing Oxford 3000 technical generation remains **3,308/3,308** stable entries.
- Targeted pronunciation QA remains artifact-level work: source resolutions/override ledger exist for the 41 sense-marker/heteronym/uppercase candidates; do not regenerate the whole Oxford 3000 pack.
- No Oxford 5000 addition is counted as audio-complete until its lexical row is production-eligible and a stable-ID MP3 + manifest/hash entry exists.
- Exact next audio action: validate/merge only verified Oxford 3000 targeted replacements, then generate audio only for newly production-eligible Oxford 5000 additions.

### Hotkey / F1 truth audit
- One shared `ShortcutFormatter` now renders shortcuts canonically as `Ctrl+Shift+B`, `Ctrl+Alt+...`, etc.
- Main F1 help, shortcut settings list and shortcut capture field now use the shared formatter instead of `Keys.ToString()`.
- Scope actions appear through the common `ShortcutManager` definition path and are rebindable/persistent by stable action ID.
- Current Spelling delete default remains **Ctrl+Shift+Delete**; regression coverage asserts the actual default display and conflict handling.
- Main Recall help now documents the six scopes, absence of Oxford C2, scope independence, and current-scope semantics of the five deck shortcuts.
- Exact next action: grouped Windows gate plus one final search/audit for any remaining user-facing raw `Keys.ToString()` output.

### Emergency blockers
- **No user-input blocker.**
- Release blocker: complete authoritative Oxford 5000 lexical inventory/translation QA is still incomplete.
- Vertical-slice verification blocker: the new scope UI/state implementation still needs a green Windows build + full self-test + published-EXE self-test on the final coherent head.
- Audio blocker: targeted Oxford 3000 replacement artifact needs final stable-ID/hash inspection; Oxford 5000 additions need audio after lexical verification.

## Parallel lanes (non-blocking)
- Core Recall/Spelling/Sentence data remain preserved; no Grammar/Story/speech-recognition/future-module work started.
- Sentence Coach low-memory SQLite path remains available but did not receive majority effort in this emergency cycle.
- Oxford 3000 semantic QA remains independent and must not block Oxford 5000 extraction/audio/scope delivery.

## Safety / release discipline
- `main` remains untouched.
- No secrets, API keys, network runtime requirement, Python runtime or Kokoro runtime were added.
- Do not send a beta automatically. A beta becomes eligible only after a coherent Windows x64 gate proves the Recall scope selector/state path end-to-end; real NVDA compatibility still requires user testing.
