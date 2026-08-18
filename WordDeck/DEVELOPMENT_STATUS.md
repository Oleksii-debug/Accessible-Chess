# WordDeck development checkpoint

Last updated: 2026-08-18
Branch: `worddeck-bootstrap` only. Never develop WordDeck on `main`.

## Emergency Oxford 5000 milestone

### Oxford lexical data
- **Runtime activation is now staged on branch head:** `DictionaryLoader.LoadEmbeddedOxford()` appends the first fail-closed canonical Oxford 5000 slice to the preserved Oxford 3000 package. Candidate production shape is **3,523 rows = 3,308 unchanged baseline rows + 215 verified canonical B2/C1 rows** from `abolish` through noun `blow`.
- The durable dictionary ID remains `oxford-3000-en-uk` intentionally so existing Recall progress migrates into the `All` workspace rather than being orphaned by a dictionary-ID change.
- `LoadEmbeddedOxford3000Baseline()` exists only as the explicit baseline contract for migration/regression testing. The main loader now targets the production-shaped beta bridge.
- Executable `SelfTest` has been rewritten to assert the emergency contract directly: exact 3,523 total, byte-for-logical-row preservation of all first 3,308 baseline entries/IDs/translations, exactly 215 appended rows, B2/C1-only additions, no C2, stable `ox5000-...` IDs, no blanks/duplicate IDs, audited `assumption` noun B2 present, and canonical endpoints `abolish` C1 -> `blow` B2.
- The previous legacy translation groups `ox5000-add-0001..0200` remain non-production IDs. Canonical IDs are deterministic normalized headword + POS + CEFR SHA-256-derived IDs.
- `ReviewedOxford5000Bootstrap` remains fail-closed: only `verified` source rows are accepted; explicit split map is required for merged POS/CEFR groups; blank translations, duplicate lexical identities, stable-ID collisions, unsupported levels and missing audited rows fail the executable.
- Current verified canonical coverage remains **215 Oxford 5000 rows**. Full official extraction beyond noun `blow` is still incomplete and is the dominant data task.
- Fresh authoritative verification on 2026-08-18 reconfirmed from Oxford Learner's Dictionaries that Oxford 5000 is the Oxford 3000 plus about 2,000 additional **B2-C1** words and that the official web list exposes CEFR and POS. No Oxford C2 vocabulary subset is to be invented.
- Exact next data action: continue source-backed extraction after noun `blow` in large lexical-row-preserving batches, isolate ambiguous POS/sense rows as `needs_second_pass`, and never block later unambiguous extraction on those rows.

### Recall Study Scope / Workspace
- Durable scope IDs remain exactly `all`, `a1`, `a2`, `b1`, `b2`, `c1`; display labels are `All Oxford 5000`, `A1`, `A2`, `B1`, `B2`, `C1`.
- Scope storage persists independent deck assignments, active deck, current card and remaining shuffle progress per dictionary/scope. Legacy Recall assignments/current card/active deck migrate losslessly into `All`; level scopes initialize eligible entries to core deck 1.
- Native keyboard/NVDA Study Scope ComboBox is implemented. Existing `Ctrl+1..5` / `Alt+1..5` remain current-scope deck switch/move actions. Stable scope actions are rebindable and default unassigned.
- The newly activated 215-row package now gives real B2 and C1 lexical rows to the runtime scope model rather than synthetic-only coverage. The grouped Windows/published-EXE gate is the next verification point.

### British offline audio
- Existing Oxford 3000 technical generation remains **3,308/3,308** stable entries.
- Targeted pronunciation QA remains 36 numbered/sense-marker candidates with 19 deterministic `ready` replacements and 17 heteronym/sense-sensitive `review` records; uppercase/acronym listening candidates remain separate.
- Canonical Oxford 5000 additions now have stable production IDs for the first 215 rows, but **canonical addition audio remains 0 generated files** at this checkpoint.
- Exact next audio action after the 3,523-row Windows gate is green: generate British MP3 only for these 215 activated canonical IDs, emit manifest + SHA-256/integrity records, then continue batch-by-batch as later lexical rows become verified. No wholesale 3,308 regeneration.
- Kokoro/Misaki remains development-only; WordDeck runtime stays offline and has no Python/API/network dependency.

### Hotkey / F1 truth audit
- Shared `ShortcutFormatter` remains the canonical display path (`Ctrl+Shift+B`, `Ctrl+Alt+...`) for F1/settings/capture UI.
- `SelfTest` now matches the current Recall registry shape: 11 Recall commands + 6 stable scope actions + 10 five-core-deck switch/move actions = **27** actions before user-created Recall decks; a user deck adds exactly two stable actions.
- Scope actions start unassigned; conflict and unsafe-key checks remain tested. `Ctrl+S` explicit save and `Ctrl+Shift+A` bulk add are asserted from code.
- Spelling delete remains **Ctrl+Shift+Delete**, not Ctrl+Alt+Delete; shared formatter tests remain in the scope test suite.

### Emergency blockers
- **No user-input blocker.**
- Full-data blocker: authoritative Oxford 5000 row-level extraction after noun `blow` is incomplete; the full official inventory cannot yet be claimed.
- Verification blocker for this exact head: the new 3,523-row runtime activation and revised executable contract have been committed, but this status entry does **not** claim a green Windows/published-EXE gate until GitHub Actions completes successfully for the new head.
- Audio blocker: first 215 canonical addition MP3s are not generated yet; targeted Oxford 3000 pronunciation replacements are not release-complete.

## Parallel lanes (non-blocking)
- Core Recall/Spelling/Sentence persisted state remains preserved. No Grammar/Story/speech-recognition/My Corrector/future-module work started.
- Sentence Coach/SQLite receives no majority effort while the emergency Oxford deliverable is incomplete.
- Oxford 3000 semantic QA remains independent and does not block Oxford 5000 extraction/audio/scope delivery.

## Safety / release discipline
- `main` remains untouched.
- Existing Oxford 3000 stable IDs/progress are explicitly regression-checked as the unchanged first 3,308 rows of the candidate package.
- No secrets, runtime network requirement, Python runtime or Kokoro runtime were added.
- No beta is sent automatically. The current branch becomes a verified emergency vertical slice only after the grouped Windows build, extended self-tests, self-contained publish and published-EXE self-test are green for the activated 3,523-row head.
