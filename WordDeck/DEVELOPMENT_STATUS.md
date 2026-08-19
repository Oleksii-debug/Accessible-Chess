# WordDeck development checkpoint

Last updated: 2026-08-19
Branch: `worddeck-bootstrap` only. Never develop WordDeck on `main`.

## Emergency Oxford 5000 milestone

### Oxford lexical data
- Current branch runtime now targets **4,232 dictionary rows = 3,308 unchanged Oxford 3000 baseline rows + 924 verified/activated Oxford 5000 additions**. Existing Oxford 3000 IDs/progress remain unchanged; durable dictionary ID remains `oxford-3000-en-uk` for lossless migration. The exact 924-addition checkpoint still requires a visible successful Windows gate before being called a verified executable checkpoint.
- Newly runtime-activated verified C1 slice: **`namely` adverb → `offspring` noun (28 rows)** from `QA/oxford5000_source_after_mutual_verified_c1_0001_0028.tsv`. All rows were already source/sense/translation checked and carry stable lexical IDs; activation is fail-closed through the shared verified-slice loader.
- Previous activated slice remains **`methodology` noun → `mutual` adjective (29 rows)**. Oxford word-list POS/CEFR is preserved; problematic lexical cases were checked against current OALD definitions rather than flattened or guessed.
- The earlier post-`mutual` staging was found to be structurally incomplete: it contained 29 rows, omitted a large B2/C1 candidate set, and incorrectly included `objective` adjective. Oxford's own Oxford 3000 material lists `objective`, so that row was removed from Oxford 5000-addition staging rather than relabelled.
- The post-`mutual` through `offspring` QA ledger accounts for **57 B2/C1 lexical candidates**. **28 C1 rows are now verified and runtime-activated**. **29 rows remain `ambiguous_source`** in `QA/oxford5000_source_after_mutual_ambiguous_b2c1_0001_0029.tsv`: their POS/CEFR is confirmed in the current official Oxford union, but exact Oxford5000-exclusive membership still needs official membership-preserving reconciliation. All 29 remain blank/fail-closed.
- Activated examples include `namely`, `nationwide`, `naval`, `niche`, `noble`, `nominate`, `non-profit`, `nonetheless`, `notorious`, `novel` adjective, `nursery`, `oblige`, `obsess`, `occurrence`, `odds`, `offering` and `offspring`. Polysemous translations preserve multiple relevant Ukrainian senses rather than flattening them.
- `ReviewedOxford5000Bootstrap.ExpectedCanonicalRows` is now **924**. The 28-row post-mutual resource is embedded explicitly by the project and the canonical bootstrap asserts presence of both boundary entries (`namely`, `offspring`) in addition to the existing ledger invariants.
- A deterministic validator, `tools/validate_oxford5000_runtime_ledger.py`, reconstructs the exact runtime Oxford additions from the C# bootstrap and embedded resources, checks stable IDs/POS/CEFR/nonblank translations/duplicates, separately counts fail-closed staged rows, and refuses to call Stage 1 complete while the global official inventory is unresolved.
- The same validator has an optional **full official reconciliation mode**: when supplied a saved official Oxford HTML snapshot it uses the existing official extractor, rejects local source/POS/CEFR rows absent from the official Oxford5000-exclusive inventory, and emits the exact unaccounted tail instead of an estimate.
- Windows CI targets the current runtime Oxford ledger and corpus-accounting artifact rather than obsolete partial canonical artifacts.
- Oxford's official current material defines Oxford 5000 as Oxford 3000 plus an additional 2,000 B2/C1 words; no Oxford C2 subset is invented.
- **Exact next data action:** obtain/use a saved official Oxford word-list source that preserves Oxford3000-vs-Oxford5000 membership, run full reconciliation to turn global `remaining` from UNKNOWN into an exact count, resolve the 29 source-ambiguous rows, and continue the global corpus independently of ambiguous entries.

### Recall Study Scope / Workspace
- Durable scope IDs: `all`, `a1`, `a2`, `b1`, `b2`, `c1`; labels: `All Oxford 5000`, `A1`, `A2`, `B1`, `B2`, `C1`.
- Independent scope assignments, active deck, current card and remaining shuffle progress are implemented. Legacy Recall state migrates into `All`; level scopes initialize eligible entries to core deck 1.
- Native keyboard/NVDA Study Scope ComboBox is implemented. Existing `Ctrl+1..5` / `Alt+1..5` operate inside the current scope. Stable scope actions are rebindable and default unassigned.
- Newly activated rows enter `All` and their CEFR scope deterministically without changing existing All-scope assignments or other scope state.
- Scope regression tests cover isolation, migration, persistence, per-scope current card/shuffle state and stable scope shortcut actions.

### British offline audio
- Oxford 3000 technical generation: **3,308/3,308**.
- Targeted Oxford 3000 QA queue remains 36 numbered/sense-marker candidates: 19 deterministic `ready`, 17 heteronym/sense-sensitive `review`; review rows are not guessed.
- A prior Oxford 5000 generation batch was built against an earlier 606-addition set; its completion/integrity is not promoted to release accounting without independent validation.
- Current runtime lexical target is **924 Oxford 5000 additions**. British audio for all 924 additions is not yet fully generated and independently validated, so full Oxford 5000 audio coverage is explicitly **not** claimed.
- The activated `methodology`→`mutual` block and new `namely`→`offspring` block have stable lexical IDs and are eligible for targeted batch audio generation. `minute` adjective must use a reviewed heteronym pronunciation override rather than naïve text reuse.
- Runtime remains offline and independent of Kokoro/Python/API/network.

### Hotkey / F1 truth audit
- Shared `ShortcutFormatter` remains the canonical display path for human-readable forms such as `Ctrl+Shift+B` and `Ctrl+Alt+F8` in F1/settings/capture UI.
- Recall registry contract remains 11 Recall commands + 6 scope actions + 10 five-core-deck switch/move actions = **27** actions before user-created Recall decks; each user deck adds two stable actions.
- Scope actions start unassigned. `Ctrl+S` explicit save and `Ctrl+Shift+A` bulk add are regression-asserted.
- Spelling delete remains **Ctrl+Shift+Delete**, not Ctrl+Alt+Delete.

### Emergency blockers
- **No user-input blocker.**
- Full official Oxford 5000 row-level extraction/reconciliation remains incomplete, so the global unaccounted tail is still **UNKNOWN**, not zero.
- Branch runtime contains **924 verified Oxford 5000 additions**; a fresh visible successful Windows build/self-test/publish gate is required before this exact code checkpoint is promoted as a verified executable checkpoint.
- **29 post-`mutual` B2/C1 rows remain source-ambiguous** and fail-closed in `QA/oxford5000_source_after_mutual_ambiguous_b2c1_0001_0029.tsv`. They are not runtime-active and have no guessed translations.
- British audio for all activated Oxford 5000 additions is not yet fully verified; do not claim full Oxford 5000 audio coverage.
- Targeted Oxford 3000 pronunciation replacements remain incomplete for 17 sense-sensitive review rows; do not guess them.

## Parallel lanes (non-blocking)
- Core Recall/Spelling/Sentence persisted state remains preserved. No Grammar/Story/speech-recognition/My Corrector work started.
- Sentence Coach/SQLite received no majority effort while emergency Oxford work remains incomplete.
- Oxford 3000 semantic QA remains independent and does not block Oxford 5000 extraction/audio/scope delivery.

## Safety / release discipline
- `main` remains untouched.
- Existing Oxford 3000 stable IDs/progress remain regression-protected as the unchanged first 3,308 rows.
- No secrets, runtime network requirement, Python runtime or Kokoro runtime were added.
- Only rows that satisfy the source, sense, translation and activation gates may be runtime-activated; ambiguous rows remain QA-only.
- No beta is sent automatically.
