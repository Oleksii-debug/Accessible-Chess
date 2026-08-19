# WordDeck development checkpoint

Last updated: 2026-08-19
Branch: `worddeck-bootstrap` only. Never develop WordDeck on `main`.

## Emergency Oxford 5000 milestone

### Oxford lexical data
- Runtime activation is now **4,030 dictionary rows = 3,308 unchanged Oxford 3000 baseline rows + 722 verified canonical B2/C1 Oxford 5000 additions**. Existing Oxford 3000 IDs/progress remain unchanged; durable dictionary ID remains `oxford-3000-en-uk` for lossless migration.
- The previously staged **29-row verified C1 slice `immense` adjective → `injustice` noun** is now embedded and activated. It uses deterministic stable IDs over lowercase `source + U+001F + POS + U+001F + CEFR`, contains no blank translations, and is admitted only through the fail-closed verified-slice loader.
- Authoritative extraction has advanced again beyond `injustice`: `oxford5000_source_after_injustice_c1_0001_0029.tsv` contains the next **29 official C1 lexical rows**, from `inmate` noun through `interim` adjective, with POS/CEFR checked against the Oxford 3000/5000 list on 2026-08-19.
- Of that new 29-row staging slice, **24 rows are `verified` and 5 are deliberately `needs_second_pass`** (`instrumental` adjective, `intake` noun, `integrity` noun, `interface` noun, `interference` noun). The five broader/polysemous rows are not runtime-activated and are not silently guessed.
- Oxford documents the Oxford 5000 as the Oxford 3000 plus 2,000 B2-C1 additions; no Oxford C2 vocabulary subset is invented.
- Earlier semantically broader C-region exclusions remain excluded pending second-pass semantic QA.
- **Exact next data action:** second-pass the five isolated I-region rows while continuing source extraction immediately after `interim` adjective; activate only verified rows in the next coherent runtime/audio checkpoint.

### Recall Study Scope / Workspace
- Durable scope IDs: `all`, `a1`, `a2`, `b1`, `b2`, `c1`; labels: `All Oxford 5000`, `A1`, `A2`, `B1`, `B2`, `C1`.
- Independent scope assignments, active deck, current card and remaining shuffle progress are implemented. Legacy Recall state migrates into `All`; level scopes initialize eligible entries to core deck 1.
- Native keyboard/NVDA Study Scope ComboBox is implemented. Existing `Ctrl+1..5` / `Alt+1..5` operate inside the current scope. Stable scope actions are rebindable and default unassigned.
- The newly activated 29 C1 rows enter `All` and `C1` deterministically without changing existing All-scope assignments.
- Scope regression tests cover isolation, migration, persistence, per-scope current card/shuffle state and stable scope shortcut actions.

### British offline audio
- Oxford 3000 technical generation: **3,308/3,308**.
- Targeted Oxford 3000 QA queue remains 36 numbered/sense-marker candidates: 19 deterministic `ready`, 17 heteronym/sense-sensitive `review`; review rows are not guessed.
- A prior Oxford 5000 generation batch was built against an earlier 606-addition set; its completion/integrity is not promoted to release accounting without independent validation.
- Runtime lexical coverage is now **722 Oxford 5000 additions**. Audio coverage for the 29 newly activated `immense`→`injustice` stable IDs has not yet been generated/validated in this checkpoint, so full Oxford 5000 audio coverage is explicitly **not** claimed.
- Runtime remains offline and independent of Kokoro/Python/API/network.

### Hotkey / F1 truth audit
- Shared `ShortcutFormatter` remains the canonical display path for human-readable forms such as `Ctrl+Shift+B` and `Ctrl+Alt+F8` in F1/settings/capture UI.
- Recall registry contract remains 11 Recall commands + 6 scope actions + 10 five-core-deck switch/move actions = **27** actions before user-created Recall decks; each user deck adds two stable actions.
- Scope actions start unassigned. `Ctrl+S` explicit save and `Ctrl+Shift+A` bulk add are regression-asserted.
- Spelling delete remains **Ctrl+Shift+Delete**, not Ctrl+Alt+Delete.

### Emergency blockers
- **No user-input blocker.**
- Full official Oxford 5000 row-level extraction remains incomplete.
- Runtime is now at **722 verified Oxford 5000 additions**; the next staged 29-row C1 slice contains **24 verified + 5 needs_second_pass** and is intentionally not activated as a mixed-status block.
- A fresh Windows self-test/build gate is required for the new 722-row runtime head before it is called a verified beta milestone.
- British audio for newly activated Oxford 5000 additions is not yet fully verified; do not claim full Oxford 5000 audio coverage.
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
