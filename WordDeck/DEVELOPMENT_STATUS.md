# WordDeck development checkpoint

Last updated: 2026-08-19
Branch: `worddeck-bootstrap` only. Never develop WordDeck on `main`.

## Emergency Oxford 5000 milestone

### Oxford lexical data
- Current branch runtime target is now **4,261 dictionary rows = 3,308 unchanged Oxford 3000 baseline rows + 953 verified/activated Oxford 5000 additions**. Existing Oxford 3000 IDs/progress remain unchanged; durable dictionary ID remains `oxford-3000-en-uk` for lossless migration. This exact 953-addition checkpoint still requires the fresh Windows gate to pass before being called a verified executable checkpoint.
- Newly activated source-backed slice: **29 B2/C1 lexical rows from `myth` noun through `offender` noun** in `QA/oxford5000_source_after_mutual_verified_b2c1_0001_0029.tsv`.
- The 29-row slice preserves Oxford POS/CEFR distinctions, including separate `nearby` adjective/adverb and `neglect` noun/verb rows. `nursing` is noun B2 according to the current official Oxford interactive list. Stable lexical IDs were retained/recomputed from source+POS+CEFR only.
- Translation QA is complete for the 29 rows. Where one English POS covers several established Oxford senses, the Ukrainian field preserves multiple principal equivalents rather than guessing a single narrow sense; examples include `nasty`, `net` adjective and `occupation` noun. Oxford Advanced Learner's Dictionary pages were used for these sense-sensitive checks.
- The retired `pending_translation_qa` ledger for these same 29 identities has been removed, so the local ledger has no staged/runtime collision.
- Previous activated slices remain `methodology` noun → `mutual` adjective (29 rows) and `namely` adverb → `offspring` noun (28 rows).
- `ReviewedOxford5000Bootstrap.ExpectedCanonicalRows` is now **953** and activation remains fail-closed: only `status=verified`, nonblank Ukrainian translation, valid B2/C1 and exact stable ID are admitted.
- `tools/validate_oxford5000_runtime_ledger.py` reconstructs the exact runtime additions from the C# bootstrap and embedded resources, checks stable IDs/POS/CEFR/nonblank translations/duplicates, separately counts staged fail-closed rows, and supports authoritative full reconciliation with `--official-html`.
- `tools/fetch_oxford5000_official_html.py` remains build/CI-only and requires a complete membership-bearing Oxford page before reconciliation. Official-source network input is not shipped in runtime artifacts.
- **Exact global remaining remains dependent on a successful authoritative reconciliation run.** Do not infer full Oxford 5000 completion from the 953 activated additions alone.

### Oxford 3000 baseline integrity
- `SelfTest.TestEmbeddedOxford()` compares every one of the first 3,308 baseline rows before/after Oxford 5000 append and requires exact ID/level/source/target preservation.
- `tools/validate_oxford3000_baseline_files.py` independently checks the eight pinned source fragments, reconstruction, metadata-aware parsing, 3,308 exact rows, unique/nonblank IDs/data and CEFR counts **A1=900, A2=872, B1=809, B2=727**.
- Windows CI emits baseline-integrity evidence including reconstructed TSV SHA-256.

### Recall Study Scope / Workspace
- Durable scope IDs: `all`, `a1`, `a2`, `b1`, `b2`, `c1`; labels: `All Oxford 5000`, `A1`, `A2`, `B1`, `B2`, `C1`.
- Independent scope assignments, active deck, current card and remaining shuffle progress are implemented. Legacy Recall state migrates into `All`; level scopes initialize eligible entries to core deck 1.
- Native keyboard/NVDA Study Scope ComboBox is implemented. Existing `Ctrl+1..5` / `Alt+1..5` operate inside the current scope. Stable scope actions are rebindable and default unassigned.
- Newly activated rows enter `All` and their CEFR scope deterministically without changing existing All-scope assignments or other scope state.
- Scope regression tests cover isolation, migration, persistence, per-scope current card/shuffle state and stable scope shortcut actions.

### British offline audio
- Oxford 3000 technical generation: **3,308/3,308**.
- Targeted Oxford 3000 QA queue remains 36 numbered/sense-marker candidates: 19 deterministic `ready`, 17 heteronym/sense-sensitive `review`; unresolved review rows are not guessed.
- A prior Oxford 5000 generation batch was built against an earlier smaller addition set; its completion/integrity is not promoted to current release accounting without independent validation.
- Current runtime lexical target is **953 Oxford 5000 additions**. British audio for all 953 additions is not yet fully generated and independently validated, so full Oxford 5000 audio coverage is explicitly **not** claimed.
- The newly activated 29-row `myth`→`offender` slice has stable lexical IDs and is now eligible for incremental Kokoro/Misaki British generation. Runtime remains offline and independent of Kokoro/Python/API/network.

### Hotkey / F1 truth audit
- Shared `ShortcutFormatter` remains the canonical display path for human-readable forms such as `Ctrl+Shift+B` and `Ctrl+Alt+F8` in F1/settings/capture UI.
- Recall registry contract remains 11 Recall commands + 6 scope actions + 10 five-core-deck switch/move actions = **27** actions before user-created Recall decks; each user deck adds two stable actions.
- Scope actions start unassigned. `Ctrl+S` explicit save and `Ctrl+Shift+A` bulk add are regression-asserted.
- Spelling delete remains **Ctrl+Shift+Delete**, not Ctrl+Alt+Delete.

### Emergency blockers / open gates
- **No user-input blocker.**
- Branch runtime now contains **953 verified Oxford 5000 additions**; a fresh successful Windows restore/build/self-test/self-contained publish/published-EXE self-test is required before this exact checkpoint is promoted as a verified executable checkpoint.
- Full official Oxford 5000 extraction is still incomplete; authoritative reconciliation must produce the exact remaining tail and later extraction must continue in large verified batches.
- British audio for all activated Oxford 5000 additions is not yet fully verified; do not claim full Oxford 5000 audio coverage.
- Targeted Oxford 3000 pronunciation replacements remain incomplete for 17 sense-sensitive review rows; do not guess them.

### Exact next action
1. Observe the single latest Windows gate for the 953-addition checkpoint and fix any fail-closed regression without touching `main`.
2. Run authoritative reconciliation to materialize the exact official unaccounted B2/C1 tail.
3. Extract/translate the next large contiguous authoritative batch while keeping ambiguous rows isolated instead of blocking later rows.
4. Queue incremental British audio only for verified stable additions, including the newly activated 29-row slice.

## Parallel lanes (non-blocking)
- Sentence/SQLite and Oxford 3000 semantic QA remain lower priority and must not delay the emergency Oxford 5000 Recall deliverable.
- Core Recall/Spelling/Sentence persisted state remains preserved. No Grammar/Story/speech-recognition/My Corrector work started.

## Safety / release discipline
- `main` remains untouched.
- Existing Oxford 3000 stable IDs/progress remain regression-protected as the unchanged first 3,308 rows.
- No secrets, runtime network requirement, Python runtime or Kokoro runtime were added. Official-source network access is build/CI-only.
- Only rows satisfying authoritative membership, source/POS/CEFR, translation QA and stable-ID gates may be runtime-activated; pending/unresolved rows remain QA-only.
- No beta is sent automatically.