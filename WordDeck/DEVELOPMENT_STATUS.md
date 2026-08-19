# WordDeck development checkpoint

Last updated: 2026-08-19
Branch: `worddeck-bootstrap` only. Never develop WordDeck on `main`.

## Emergency Oxford 5000 milestone

### Oxford lexical data
- Current branch code now targets **4,175 dictionary rows = 3,308 unchanged Oxford 3000 baseline rows + 867 verified canonical B2/C1 Oxford 5000 additions**. Existing Oxford 3000 IDs/progress remain unchanged; durable dictionary ID remains `oxford-3000-en-uk` for lossless migration. This 867-addition checkpoint still requires the fresh Windows gate below before being called a verified executable checkpoint.
- Three consecutive complete C1 slices are now `verified`, embedded and activated: **`laser` noun → `limb` noun (29)**, **`line-up` noun → `manipulate` verb (29)**, and **`manipulation` noun → `merit` noun (29)**. Stable IDs/POS/CEFR are preserved and polysemous rows retain explicit source-backed Ukrainian coverage instead of guessed single-sense collapse.
- Official extraction has advanced another **29 C1 lexical rows after `merit`**, staged in `oxford5000_source_after_merit_c1_0001_0029.tsv`: `methodology` noun → `mutual` adjective. Every staged row has a deterministic stable ID and Oxford word-list POS/CEFR confirmation; all remain `pending_translation_qa` with blank translations and are therefore fail-closed from runtime activation.
- Oxford's official current word-list/about material continues to define Oxford 5000 as Oxford 3000 plus advanced B2/C1 additions; no Oxford C2 subset is invented.
- **Exact next data action:** definition-check/translate the staged `methodology`→`mutual` slice in source-backed batches, continue official extraction after `mutual` independently of any ambiguous row, then activate only rows that satisfy the required nonblank/source-checked threshold.

### Recall Study Scope / Workspace
- Durable scope IDs: `all`, `a1`, `a2`, `b1`, `b2`, `c1`; labels: `All Oxford 5000`, `A1`, `A2`, `B1`, `B2`, `C1`.
- Independent scope assignments, active deck, current card and remaining shuffle progress are implemented. Legacy Recall state migrates into `All`; level scopes initialize eligible entries to core deck 1.
- Native keyboard/NVDA Study Scope ComboBox is implemented. Existing `Ctrl+1..5` / `Alt+1..5` operate inside the current scope. Stable scope actions are rebindable and default unassigned.
- Newly activated C1 rows enter `All` and `C1` deterministically without changing existing All-scope assignments or any other scope state.
- Scope regression tests cover isolation, migration, persistence, per-scope current card/shuffle state and stable scope shortcut actions.

### British offline audio
- Oxford 3000 technical generation: **3,308/3,308**.
- Targeted Oxford 3000 QA queue remains 36 numbered/sense-marker candidates: 19 deterministic `ready`, 17 heteronym/sense-sensitive `review`; review rows are not guessed.
- A prior Oxford 5000 generation batch was built against an earlier 606-addition set; its completion/integrity is not promoted to release accounting without independent validation.
- Current branch lexical target is **867 Oxford 5000 additions**. British audio for all 867 additions is not yet fully generated and independently validated, so full Oxford 5000 audio coverage is explicitly **not** claimed.
- The newly activated 87-row C1 block (`laser`→`merit`) has stable lexical IDs and is eligible for targeted batch audio generation. Audio remains keyed by stable dictionary+entry ID and must not block later lexical extraction.
- Runtime remains offline and independent of Kokoro/Python/API/network.

### Hotkey / F1 truth audit
- Shared `ShortcutFormatter` is the canonical display path for human-readable forms such as `Ctrl+Shift+B` and `Ctrl+Alt+F8` in F1/settings/capture UI.
- Recall registry contract remains 11 Recall commands + 6 scope actions + 10 five-core-deck switch/move actions = **27** actions before user-created Recall decks; each user deck adds two stable actions.
- Scope actions start unassigned. `Ctrl+S` explicit save and `Ctrl+Shift+A` bulk add are regression-asserted.
- Spelling delete remains **Ctrl+Shift+Delete**, not Ctrl+Alt+Delete.

### Emergency blockers
- **No user-input blocker.**
- Full official Oxford 5000 row-level extraction remains incomplete.
- The branch code now contains **867 verified Oxford 5000 additions**, but a fresh Windows build/self-test gate is still required before this exact code checkpoint is promoted as a verified executable checkpoint.
- The next **29 C1 rows (`methodology`→`mutual`) are source-staged only** and remain excluded from runtime until translation/definition QA is complete.
- British audio for all currently activated Oxford 5000 additions is not yet fully verified; do not claim full Oxford 5000 audio coverage.
- Targeted Oxford 3000 pronunciation replacements remain incomplete for 17 sense-sensitive review rows; do not guess them.

## Parallel lanes (non-blocking)
- Core Recall/Spelling/Sentence persisted state remains preserved. No Grammar/Story/speech-recognition/My Corrector work started.
- Sentence Coach/SQLite received no majority effort while emergency Oxford work remains incomplete.
- Oxford 3000 semantic QA remains independent and does not block Oxford 5000 extraction/audio/scope delivery.

## Safety / release discipline
- `main` remains untouched.
- Existing Oxford 3000 stable IDs/progress remain regression-protected as the unchanged first 3,308 rows.
- No secrets, runtime network requirement, Python runtime or Kokoro runtime were added.
- Only source-checked rows whose translations satisfy the project threshold may be runtime-activated; ambiguous/pending rows remain QA-only.
- No beta is sent automatically.