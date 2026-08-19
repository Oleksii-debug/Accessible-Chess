# WordDeck development checkpoint

Last updated: 2026-08-19
Branch: `worddeck-bootstrap` only. Never develop WordDeck on `main`.

## Emergency Oxford 5000 milestone

### Oxford lexical data
- Runtime activation remains **4,088 dictionary rows = 3,308 unchanged Oxford 3000 baseline rows + 780 verified canonical B2/C1 Oxford 5000 additions**. Existing Oxford 3000 IDs/progress remain unchanged; durable dictionary ID remains `oxford-3000-en-uk` for lossless migration.
- The next complete **29-row C1 source-backed slice, `laser` noun → `limb` noun, has now completed translation/definition QA** in `oxford5000_source_after_large_scale_c1_0001_0029.tsv`. All 29 rows are `verified`, retain deterministic stable IDs and Oxford POS/CEFR distinctions, and broad/polysemous entries such as `latter`, `lawn`, `leak`, `leap`, `legacy`, `legitimate`, `liable`, `liberal`, `liberty` were not collapsed to a guessed single sense.
- These 29 newly verified rows are intentionally **not yet runtime-activated** in this checkpoint: the current bootstrap still embeds 780 additions, so the shipped/runtime count is not overstated before a coherent code/self-test activation commit.
- Authoritative source extraction has advanced another **29 official C1 lexical rows** beyond `limb`: `oxford5000_source_after_limb_c1_0001_0029.tsv` stages `line-up` noun → `manipulate` verb with deterministic stable IDs and Oxford list POS/CEFR confirmation. These rows are `pending_translation_qa` and are not runtime-activated.
- Oxford documents the Oxford 5000 as the Oxford 3000 plus B2-C1 additions; no Oxford C2 vocabulary subset is invented.
- Earlier semantically broader exclusions remain excluded pending second-pass semantic QA.
- **Exact next data action:** activate the verified `laser`→`limb` slice in the canonical bootstrap together with its exact-count/self-test update as one coherent code checkpoint; in parallel definition-check/translate the staged `line-up`→`manipulate` slice and continue official extraction after `manipulate` without waiting on isolated ambiguities.

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
- Runtime lexical coverage remains **780 Oxford 5000 additions**. British audio for all 780 activated additions is not yet fully generated and independently validated, so full Oxford 5000 audio coverage is explicitly **not** claimed.
- The newly verified `laser`→`limb` rows are now stable enough for batch audio generation once runtime activation is committed; audio generation must remain keyed by stable dictionary+entry ID and must not block later lexical extraction.
- Runtime remains offline and independent of Kokoro/Python/API/network.

### Hotkey / F1 truth audit
- Shared `ShortcutFormatter` remains the canonical display path for human-readable forms such as `Ctrl+Shift+B` and `Ctrl+Alt+F8` in F1/settings/capture UI.
- Recall registry contract remains 11 Recall commands + 6 scope actions + 10 five-core-deck switch/move actions = **27** actions before user-created Recall decks; each user deck adds two stable actions.
- Scope actions start unassigned. `Ctrl+S` explicit save and `Ctrl+Shift+A` bulk add are regression-asserted.
- Spelling delete remains **Ctrl+Shift+Delete**, not Ctrl+Alt+Delete.

### Emergency blockers
- **No user-input blocker.**
- Full official Oxford 5000 row-level extraction remains incomplete.
- Runtime remains at **780 verified Oxford 5000 additions**; an additional 29 (`laser`→`limb`) have passed lexical/translation QA and await coherent runtime activation, while the following 29 (`line-up`→`manipulate`) are source-staged and pending translation QA.
- A fresh Windows build/self-test gate is required after the next runtime activation commit before a new beta checkpoint is called verified.
- British audio for all 780 currently activated Oxford 5000 additions is not yet fully verified; do not claim full Oxford 5000 audio coverage.
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