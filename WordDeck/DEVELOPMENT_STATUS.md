# WordDeck development checkpoint

Last updated: 2026-08-19
Branch: `worddeck-bootstrap` only. Never develop WordDeck on `main`.

## Emergency Oxford 5000 milestone

### Oxford lexical data
- Current branch runtime targets **4,232 dictionary rows = 3,308 unchanged Oxford 3000 baseline rows + 924 verified/activated Oxford 5000 additions**. Existing Oxford 3000 IDs/progress remain unchanged; durable dictionary ID remains `oxford-3000-en-uk` for lossless migration. The exact 924-addition checkpoint still requires a visible successful Windows gate before being called a verified executable checkpoint.
- Newly runtime-activated verified C1 slice: **`namely` adverb → `offspring` noun (28 rows)** from `QA/oxford5000_source_after_mutual_verified_c1_0001_0028.tsv`. All rows carry stable lexical IDs and nonblank source/sense-reviewed Ukrainian translations; activation is fail-closed through the shared verified-slice loader.
- Previous activated slice remains **`methodology` noun → `mutual` adjective (29 rows)**.
- The earlier post-`mutual` staging was structurally incomplete: it omitted B2/C1 candidates and incorrectly included `objective` adjective. `objective` was removed from Oxford 5000-addition staging because Oxford's own Oxford 3000 material contains it.
- A current **official Oxford University Press PDF, `The Oxford 5000 by CEFR level`, explicitly lists the additional 2,000 B2/C1 words beyond the Oxford 3000**. This authoritative membership source resolves the previous third-party-membership uncertainty for the 29 post-`mutual` candidates.
- The old `QA/oxford5000_source_after_mutual_ambiguous_b2c1_0001_0029.tsv` ledger has been retired. Its 29 rows now live in `QA/oxford5000_source_after_mutual_pending_b2c1_0001_0029.tsv` as **authoritative-membership-confirmed but `pending_translation_qa`**, with blank Ukrainian translations and no runtime activation.
- Official reconciliation corrected one concrete structural error in that 29-row set: `nursing` is **adjective B2**, not noun B2. Its stable lexical ID was recomputed accordingly. No guessed translation was introduced.
- `ReviewedOxford5000Bootstrap.ExpectedCanonicalRows` remains **924**. The 29 pending rows are not embedded and are not runtime-active.
- `tools/validate_oxford5000_runtime_ledger.py` reconstructs the exact runtime Oxford additions from the C# bootstrap and embedded resources, checks stable IDs/POS/CEFR/nonblank translations/duplicates, separately counts staged fail-closed rows, and supports full authoritative reconciliation with `--official-html`.
- `tools/fetch_oxford5000_official_html.py` now provides a build/CI-only, fail-closed fetch of the official Oxford 3000/5000 page. It requires a complete membership-bearing HTML source with `data-hw`, `data-ox3000` and `data-ox5000` attributes. The fetched HTML remains transient build input and is not shipped or uploaded as a release artifact.
- Windows CI now feeds that authoritative HTML into the full reconciliation pass and emits the exact runtime ledger, corpus accounting and unaccounted ledger. A green run can therefore no longer hide `global_remaining_unaccounted=UNKNOWN`.
- **Exact global remaining is still reported as UNKNOWN in this checkpoint until the new Windows run successfully obtains and reconciles the authoritative membership-bearing HTML.** Do not infer completion from the known 924+29 rows alone.

### Oxford 3000 baseline integrity
- `SelfTest.TestEmbeddedOxford()` already compares every one of the first 3,308 baseline rows before/after Oxford 5000 append and requires exact ID/level/source/target preservation.
- New `tools/validate_oxford3000_baseline_files.py` adds an independent source-file gate: exact eight-fragment set, pinned Git blob identities, Windows CRLF normalization, base64/gzip reconstruction, metadata-aware TSV parsing, 3,308 exact rows, unique/nonblank IDs/data, and exact CEFR counts **A1=900, A2=872, B1=809, B2=727**.
- Windows CI emits `oxford3000-baseline-integrity.tsv` with row/count evidence and the reconstructed baseline TSV SHA-256.

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
- The activated `methodology`→`mutual` and `namely`→`offspring` blocks have stable lexical IDs and are eligible for targeted batch audio generation. `minute` adjective must use a reviewed heteronym pronunciation override rather than naïve text reuse.
- Runtime remains offline and independent of Kokoro/Python/API/network.

### Hotkey / F1 truth audit
- Shared `ShortcutFormatter` remains the canonical display path for human-readable forms such as `Ctrl+Shift+B` and `Ctrl+Alt+F8` in F1/settings/capture UI.
- Recall registry contract remains 11 Recall commands + 6 scope actions + 10 five-core-deck switch/move actions = **27** actions before user-created Recall decks; each user deck adds two stable actions.
- Scope actions start unassigned. `Ctrl+S` explicit save and `Ctrl+Shift+A` bulk add are regression-asserted.
- Spelling delete remains **Ctrl+Shift+Delete**, not Ctrl+Alt+Delete.

### Emergency blockers / open gates
- **No user-input blocker.**
- The authoritative membership source has now been identified, but a successful full machine reconciliation has not yet been observed through the available GitHub connector; exact global remaining therefore stays **UNKNOWN** in the developer report until machine evidence exists.
- Branch runtime contains **924 verified Oxford 5000 additions**; a fresh visible successful Windows restore/build/self-test/self-contained publish/published-EXE self-test is still required before this exact checkpoint is promoted as a verified executable checkpoint.
- **29 post-`mutual` B2/C1 rows are now membership-confirmed and `pending_translation_qa`**, not `ambiguous_source`. They remain outside runtime and have blank translations.
- The available GitHub connector does not currently expose push-triggered workflow-run results for this branch; empty combined-status/PR-run lookups are an evidence-visibility limitation, not a CI PASS or FAIL claim.
- British audio for all activated Oxford 5000 additions is not yet fully verified; do not claim full Oxford 5000 audio coverage.
- Targeted Oxford 3000 pronunciation replacements remain incomplete for 17 sense-sensitive review rows; do not guess them.

## Parallel lanes (non-blocking)
- `05_AUTO_DATA_FACTORY` and `06_AUTO_CONTENT_QA` were still empty at the latest Work check; broad harvesting/first-line linguistic QA remains owned by those automation lanes rather than duplicated here.
- Work remains the sole canonical GitHub integrator and may perform deterministic integration, authoritative reconciliation and targeted repair of rejected/ambiguous rows.
- Core Recall/Spelling/Sentence persisted state remains preserved. No Grammar/Story/speech-recognition/My Corrector work started.
- Oxford 3000 semantic QA remains independent and does not block Oxford 5000 extraction/audio/scope delivery.

## Safety / release discipline
- `main` remains untouched.
- Existing Oxford 3000 stable IDs/progress remain regression-protected as the unchanged first 3,308 rows.
- No secrets, runtime network requirement, Python runtime or Kokoro runtime were added. Official-source network access is build/CI-only.
- Only rows satisfying authoritative membership, source/sense/POS/CEFR, translation QA and stable-ID gates may be runtime-activated; pending/unresolved rows remain QA-only.
- No beta is sent automatically.
