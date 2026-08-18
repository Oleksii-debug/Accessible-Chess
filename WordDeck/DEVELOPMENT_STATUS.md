# WordDeck development checkpoint

Last updated: 2026-08-18
Branch: `worddeck-bootstrap` only. Never develop WordDeck on `main`.

## Emergency Oxford 5000 milestone

### Oxford lexical data
- Embedded production dictionary remains the verified Oxford 3000 baseline: **3,308 lexical rows**, A1-B2. Do not claim Oxford 5000 complete yet.
- Oxford 5000 additions **0001-0100** were previously translated/reviewed.
- Source-backed second-pass verification is now complete through **0200**. Existing slices 0101-0120 and 0121-0140 remain `verified`; the new 0141-0200 slice contains **60/60 `verified` rows**, with no blank, pending or guessed production translation.
- The 0141-0200 pass preserves the extracted Oxford POS/CEFR metadata exactly and explicitly resolves the difficult polysemous/sense-sensitive rows including `bass1`, noun/verb `bat`, `bay`, `backing`, `behalf`, `blast` and noun `blow` rather than collapsing them silently.
- The fail-closed second-pass validator now checks all three source-backed slices 0101-0120, 0121-0140 and 0141-0200 in its self-test: exact ordered stable IDs, no duplicates, no POS/CEFR/source drift from the extraction batch, B2/C1-only additions, nonblank Ukrainian, `verified` status and explicit authoritative Oxford source evidence.
- Therefore the first **200 Oxford 5000 additions** have completed the project's current translation/source-review threshold. They are not yet counted in the embedded production dictionary until the production merge path and subsequent Windows gate are verified.
- Remaining authoritative extraction/QA after 0200 is incomplete. C1 must come only from Oxford 5000 additions. No Oxford C2 scope or invented C2 entries.
- Exact next data action: continue authoritative Oxford 5000 extraction beyond 0200 in a large batch, preserving distinct POS/sense rows and isolating ambiguities without blocking later rows; then merge only fully verified additions into the production dictionary.

### Recall Study Scope / Workspace
- Durable scope IDs are exactly: `all`, `a1`, `a2`, `b1`, `b2`, `c1`; display labels are `All Oxford 5000`, `A1`, `A2`, `B1`, `B2`, `C1`.
- Scope storage persists independent **deck assignments, active deck, current card and remaining shuffle progress** for every dictionary/scope.
- Legacy Recall assignments/current card/active deck migrate losslessly into `All`; level scopes contain only exact CEFR rows and initialize eligible entries to core deck 1.
- Nested scope dictionaries are normalized after JSON reload with case-insensitive keys, invalid deck repair and invalid current-card repair. Existing `state.json` + recovery backup behavior remains intact.
- Main Recall UI has a native WinForms **Study scope ComboBox** with keyboard/NVDA-accessible name and description. Switching scope restores that scope's active deck/current card/shuffle progress and announces scope + total.
- Current-scope counts are shown for all decks with a clear scope total.
- Existing `Ctrl+1..5` and `Alt+1..5` continue to switch/move among the shared five core decks, but operate only inside the CURRENT scope.
- Stable rebindable actions `recall_scope_<scopeId>` exist for all six scopes and default to `Unassigned`.
- Custom pasted cards remain deliberately restricted to `All Oxford 5000` so A1-C1 workspaces remain official CEFR subsets. Existing custom-deck definitions remain usable; scope assignments migrate safely if a user deck is deleted.
- Regression coverage is wired into `--self-test`: legacy-to-All migration, exact CEFR filtering, independent assignments, independent active deck/current card/shuffle, JSON round-trip persistence, ineligible-entry rejection, all six dynamic scope actions, rebinding/conflict rejection and canonical shortcut formatting.
- **Verification state:** implementation is landed on `worddeck-bootstrap`; do not call the vertical slice user-testable until the grouped Windows build/self-test/published-EXE gate is green for the final coherent beta head.
- Exact next scope action: use the next coherent production-data merge as the grouped Windows gate checkpoint, then do a native-focus/NVDA-oriented code audit before any beta is surfaced.

### British offline audio
- Existing Oxford 3000 technical generation remains **3,308/3,308** stable entries.
- Aggregate structural QA remains complete for 3,308 files, but pronunciation-content release is still blocked on the targeted candidate set rather than wholesale regeneration.
- Current durable override state: 36 numbered/sense-marker candidates are in the ledger, split into **19 `ready`** deterministic replacements and **17 `review`** heteronym/sense-sensitive records; **5 uppercase/acronym candidates** remain a separate listening/letter-name QA set.
- No Oxford 5000 addition is counted as audio-complete until its lexical row is production-eligible and a stable-ID MP3 + manifest/hash entry exists.
- Exact next audio action: finish/validate targeted Oxford 3000 replacements, then generate British MP3 only for newly merged verified Oxford 5000 additions; keep Kokoro/Misaki development-only and runtime fully offline.

### Hotkey / F1 truth audit
- One shared `ShortcutFormatter` renders shortcuts canonically as `Ctrl+Shift+B`, `Ctrl+Alt+...`, etc.
- Main F1 help, shortcut settings list and shortcut capture field use the shared formatter instead of raw `Keys.ToString()`.
- Scope actions appear through the common `ShortcutManager` definition path and are rebindable/persistent by stable action ID.
- Current Spelling delete default remains **Ctrl+Shift+Delete**; regression coverage asserts the actual default display and conflict handling.
- Main Recall help documents the six scopes, absence of Oxford C2, scope independence, and current-scope semantics of the five deck shortcuts.
- Repository code search in this checkpoint found no remaining literal `Keys.ToString` user-facing path; the grouped Windows/self-test gate remains the final executable truth check.

### Emergency blockers
- **No user-input blocker.**
- Release blocker: authoritative extraction/translation QA for Oxford 5000 additions **0201 onward** is still incomplete, and the verified additions are not yet embedded in production.
- Vertical-slice verification blocker: scope UI/state needs a green grouped Windows build + full self-test + published-EXE self-test on a coherent head that also contains production-eligible Oxford 5000 data.
- Audio blocker: targeted Oxford 3000 pronunciation replacements are not yet release-complete; Oxford 5000 additions need stable-ID audio after production merge.

## Parallel lanes (non-blocking)
- Core Recall/Spelling/Sentence data remain preserved; no Grammar/Story/speech-recognition/future-module work started.
- Sentence Coach low-memory SQLite path remains available but did not receive majority effort in this emergency cycle.
- Oxford 3000 semantic QA remains independent and does not block Oxford 5000 extraction/audio/scope delivery.
- Oxford 3000 translation-QA checkpoint remains separately at 240 reviewed entries; this emergency run did not consume time extending that lane.

## Safety / release discipline
- `main` remains untouched.
- No secrets, API keys, network runtime requirement, Python runtime or Kokoro runtime were added.
- Do not send a beta automatically. A beta becomes eligible only after a coherent Windows x64 gate proves the Recall scope selector/state path end-to-end with production-eligible Oxford 5000 data; real NVDA compatibility still requires user testing.
