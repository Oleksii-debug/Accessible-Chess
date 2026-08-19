# WordDeck development checkpoint

Last updated: 2026-08-19
Branch: `worddeck-bootstrap` only. Never develop WordDeck on `main`.

## Emergency Oxford 5000 milestone

### Oxford lexical data
- Runtime activation remains **4,001 dictionary rows = 3,308 unchanged Oxford 3000 baseline rows + 693 source-reviewed canonical B2/C1 Oxford 5000 additions**. Existing Oxford 3000 IDs/progress remain unchanged; durable dictionary ID remains `oxford-3000-en-uk` for lossless migration.
- Source-backed extraction has now advanced to **722 reviewed Oxford 5000 additions**: a new **29-row verified C1 staging slice** runs from `immense` adjective through `injustice` noun immediately after the previously activated `imagery` noun. The new source ledger is `oxford5000_source_after_imagery_c1_0001_0029.tsv`.
- Oxford source/POS/CEFR checks were revalidated on 2026-08-19 against the official Oxford 3000/5000 list. Oxford documents the 5000 as the Oxford 3000 plus 2,000 B2-C1 additions; no Oxford C2 vocabulary subset is invented.
- The new staging slice preserves one row per official lexical POS/CEFR record, uses deterministic stable IDs over lowercase `source + U+001F + POS + U+001F + CEFR`, contains no blank translations and marks every admitted row `verified`. It is intentionally staged separately until the next coherent runtime/audio checkpoint updates activation and regression totals together.
- Earlier five semantically broader C-region rows (`corrupt` adjective, `corruption` noun, `coup` noun, `cult` adjective, `cult` noun) remain excluded pending second-pass semantic QA.
- **Exact next data action:** activate the verified 29-row `immense`→`injustice` slice in the runtime ledger, then continue authoritative C1 extraction immediately after `injustice` noun in another large source-backed batch; isolate ambiguity rather than blocking later extraction.

### Recall Study Scope / Workspace
- Durable scope IDs: `all`, `a1`, `a2`, `b1`, `b2`, `c1`; labels: `All Oxford 5000`, `A1`, `A2`, `B1`, `B2`, `C1`.
- Independent scope assignments, active deck, current card and remaining shuffle progress are implemented. Legacy Recall state migrates into `All`; level scopes initialize eligible entries to core deck 1.
- Native keyboard/NVDA Study Scope ComboBox is implemented. Existing `Ctrl+1..5` / `Alt+1..5` operate inside the current scope. Stable scope actions are rebindable and default unassigned.
- Newly activated C1 rows enter `All` and `C1` deterministically without changing existing All-scope assignments.
- Scope regression tests cover isolation, migration, persistence, per-scope current card/shuffle state and stable scope shortcut actions.

### British offline audio
- Oxford 3000 technical generation: **3,308/3,308**.
- Targeted Oxford 3000 QA queue remains 36 numbered/sense-marker candidates: 19 deterministic `ready`, 17 heteronym/sense-sensitive `review`; review rows are not guessed.
- The previously requested Oxford 5000 batch was built against the then-current **606** verified additions. Its completion/integrity has not been independently confirmed in this run, so release accounting remains fail-closed rather than assuming coverage.
- Runtime/export audio ledger remains **693 activated Oxford 5000 additions**; the newly reviewed 29 rows are staged lexical data and are not yet claimed as generated audio. The next coherent audio checkpoint must first activate them and then validate/generate only missing stable IDs against the resulting 722-row verified set.
- Runtime remains offline and independent of Kokoro/Python/API/network.

### Hotkey / F1 truth audit
- Shared `ShortcutFormatter` remains the canonical display path for human-readable forms such as `Ctrl+Shift+B` and `Ctrl+Alt+F8` in F1/settings/capture UI.
- Recall registry contract remains 11 Recall commands + 6 scope actions + 10 five-core-deck switch/move actions = **27** actions before user-created Recall decks; each user deck adds two stable actions.
- Scope actions start unassigned. `Ctrl+S` explicit save and `Ctrl+Shift+A` bulk add are regression-asserted.
- Spelling delete remains **Ctrl+Shift+Delete**, not Ctrl+Alt+Delete.

### Emergency blockers
- **No user-input blocker.**
- Full official Oxford 5000 row-level extraction remains incomplete: **722 source-reviewed additions are now represented in source/QA ledgers, 693 of them are runtime-activated**.
- A fresh Windows self-test/build gate is still required for the current 693-row runtime head before that head is called a verified beta milestone; the new 29-row staging file itself does not alter runtime behavior yet.
- British audio for the newly activated/staged additions is not yet fully verified; do not claim full Oxford 5000 audio coverage.
- Targeted Oxford 3000 pronunciation replacements remain incomplete for 17 sense-sensitive review rows; do not guess them.

## Parallel lanes (non-blocking)
- Core Recall/Spelling/Sentence persisted state remains preserved. No Grammar/Story/speech-recognition/My Corrector work started.
- Sentence Coach/SQLite received no majority effort while emergency Oxford work remains incomplete.
- Oxford 3000 semantic QA remains independent and does not block Oxford 5000 extraction/audio/scope delivery.

## Safety / release discipline
- `main` remains untouched.
- Existing Oxford 3000 stable IDs/progress remain regression-protected as the unchanged first 3,308 rows.
- No secrets, runtime network requirement, Python runtime or Kokoro runtime were added.
- Only source-checked rows may be runtime-activated; ambiguous/pending rows remain QA-only.
- No beta is sent automatically.
