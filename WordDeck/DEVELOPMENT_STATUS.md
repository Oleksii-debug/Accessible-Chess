# WordDeck development checkpoint

Last updated: 2026-08-18
Branch: `worddeck-bootstrap` only. Never develop WordDeck on `main`.

## Emergency Oxford 5000 milestone

### Oxford lexical data
- Embedded production dictionary remains the verified Oxford 3000 baseline: **3,308 lexical rows**, A1-B2. No Oxford 5000 addition has yet been promoted into the embedded production dictionary in this checkpoint.
- The previously reviewed `ox5000-add-0001..0200` material is now explicitly classified as **legacy translation-working groups**, not canonical production lexical rows. Its Ukrainian work remains reusable, but its old numeric IDs must not be promoted directly.
- A source-structure audit against the current official Oxford 3000/5000 list found **13 merged POS groups** in the old staging (`abuse`, `acid`, `advocate`, `alert`, `alien`, `alike`, `amateur`, `assault`, `attribute`, `besides`, `bid`, `blast`, `blend`) plus one omitted official row, `assumption` noun B2.
- After splitting those confirmed merged groups and restoring `assumption`, the old alphabetical span from `abolish` through noun `blow` corresponds to **215 separate official Oxford lexical rows**, not 200. The detailed reconciliation is in `QA/OXFORD5000_STRUCTURE_AUDIT_0001_0200.md`.
- The old translation second-pass material is source-reviewed through old group `0200`, including the difficult polysemous items, but it is **not production-eligible until remapped to canonical per-row identities**. This distinction prevents a false claim that 200 official Oxford additions are ready.
- New development tool `tools/extract_oxford5000_official.py` implements the corrected row-preserving model using Python standard library only. It consumes saved official Oxford list HTML, excludes Oxford 3000 membership, preserves each B2/C1 POS row separately, rejects unexpected levels such as C2, and derives order-independent candidate stable IDs from headword + POS + CEFR + official definition path.
- The public historical `winterdl/oxford-5000-vocabulary-audio-definition` project was evaluated only as a QA/reference aid; because no usable license was identified, no code/data/audio is incorporated and it is not an authoritative source. The current Oxford page remains source of truth.
- C1 must come only from official Oxford 5000 additions. No Oxford C2 scope or invented C2 entries.
- Exact next data action: run the canonical extractor against an authoritative saved current Oxford page, reconcile the first 215 canonical rows with the already reviewed Ukrainian material, then continue authoritative extraction beyond noun `blow` in large row-preserving batches. Only canonical verified rows may be embedded.

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
- **Verification state:** implementation is landed on `worddeck-bootstrap`; do not call the vertical slice user-testable until a grouped Windows build/self-test/published-EXE gate is green on a coherent head containing canonical production Oxford 5000 additions.
- Exact next scope action: keep the architecture unchanged while canonical Oxford rows are prepared; use the first coherent production-data merge as the scope end-to-end Windows/NVDA-oriented checkpoint.

### British offline audio
- Existing Oxford 3000 technical generation remains **3,308/3,308** stable entries.
- Aggregate structural QA remains complete for 3,308 files, but pronunciation-content release is still blocked on the targeted candidate set rather than wholesale regeneration.
- Current durable override state: 36 numbered/sense-marker candidates are in the ledger, split into **19 `ready`** deterministic replacements and **17 `review`** heteronym/sense-sensitive records; **5 uppercase/acronym candidates** remain a separate listening/letter-name QA set.
- Oxford 5000 addition audio generation is intentionally **paused until canonical per-row stable IDs exist**. Generating against the old merged staging IDs would create disposable/wrongly keyed MP3s.
- No Oxford 5000 addition is counted as audio-complete until its canonical lexical row is production-eligible and a stable-ID MP3 + manifest/hash entry exists.
- Exact next audio action: finish/validate targeted Oxford 3000 replacements independently; after canonical Oxford 5000 IDs are established, generate British MP3 only for verified canonical additions. Kokoro/Misaki remains development-only and runtime stays fully offline.

### Hotkey / F1 truth audit
- One shared `ShortcutFormatter` renders shortcuts canonically as `Ctrl+Shift+B`, `Ctrl+Alt+...`, etc.
- Main F1 help, shortcut settings list and shortcut capture field use the shared formatter instead of raw `Keys.ToString()`.
- Scope actions appear through the common `ShortcutManager` definition path and are rebindable/persistent by stable action ID.
- Current Spelling delete default remains **Ctrl+Shift+Delete**; regression coverage asserts the actual default display and conflict handling.
- Main Recall help documents the six scopes, absence of Oxford C2, scope independence, and current-scope semantics of the five deck shortcuts.
- Repository code search in this checkpoint found no remaining literal `Keys.ToString` user-facing path; the grouped Windows/self-test gate remains the final executable truth check.

### Emergency blockers
- **No user-input blocker.**
- Release blocker: old Oxford 5000 translation groups must first be canonicalized into one official row per POS/CEFR entry; authoritative extraction beyond noun `blow` remains incomplete.
- Vertical-slice verification blocker: no canonical Oxford 5000 additions are embedded yet, so the scope UI/state implementation has not been proven on the actual new production dataset.
- Audio blocker: targeted Oxford 3000 pronunciation replacements are not yet release-complete, and Oxford 5000 audio must wait for canonical stable IDs.

## Parallel lanes (non-blocking)
- Core Recall/Spelling/Sentence data remain preserved; no Grammar/Story/speech-recognition/future-module work started.
- Sentence Coach low-memory SQLite path remains available but received no majority effort in this emergency cycle.
- Oxford 3000 semantic QA remains independent and does not block Oxford 5000 extraction/audio/scope delivery.
- Oxford 3000 translation-QA checkpoint remains separately at 240 reviewed entries; this emergency run did not consume time extending that lane.

## Safety / release discipline
- `main` remains untouched.
- Existing Oxford 3000 stable IDs/progress remain untouched; the flawed Oxford 5000 staging was caught before production embedding.
- No secrets, API keys, network runtime requirement, Python runtime or Kokoro runtime were added.
- Do not send a beta automatically. A beta becomes eligible only after canonical verified Oxford 5000 rows are embedded and a coherent Windows x64 gate proves the Recall scope selector/state path end-to-end; real NVDA compatibility still requires user testing.
