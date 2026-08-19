# WordDeck development checkpoint

Last updated: 2026-08-19
Branch: `worddeck-bootstrap` only. Never develop WordDeck on `main`.

## Emergency Oxford 5000 milestone

### Oxford lexical data
- Grouped runtime activation is committed for **3,914 dictionary rows = 3,308 unchanged Oxford 3000 baseline rows + 606 source-reviewed canonical B2/C1 Oxford 5000 additions**. Existing Oxford 3000 IDs/progress remain unchanged; durable dictionary ID remains `oxford-3000-en-uk` for lossless migration.
- The grouped activation includes the previous 490 runtime additions plus four newer 29-row source-backed slices: `donor`→`embarrassment`, `embassy`→`equality`, `equation`→`explosive` adjective, and `explosive` noun→`flesh` noun.
- Bootstrap is fail-closed at **606** canonical Oxford 5000 rows and embeds all reviewed QA resources. The historical `deployment` enumeration tail is preserved only for old regression-order compatibility; stable lexical IDs, not row positions, remain the durable identity contract.
- The activated spans preserve explicit lexical rows rather than collapsing spellings: examples include `ease` noun/verb, `excess` adjective/noun, `explosive` adjective/noun, `feminist` adjective/noun, `filter` noun/verb and `fine` noun/verb. Stable IDs are deterministic SHA-256 identities over source/POS/CEFR.
- Oxford official list confirmation for the E/F spans was rechecked on 2026-08-19 against the official Oxford 3000/5000 list. Oxford confirms that the Oxford 5000 adds 2,000 B2-C1 items beyond the Oxford 3000; no Oxford C2 workspace is invented.
- Every activated source row must be `verified`, have nonblank Ukrainian translation, supported B2/C1 CEFR, unique lexical identity and a stable ID recomputed from lowercase `source + U+001F + POS + U+001F + CEFR` using SHA-256.
- Earlier POS splits for `dispute` noun/verb and `distress` noun/verb remain distinct stable lexical entries; no POS/sense collapse was introduced.
- Five semantically broader earlier C-region rows (`corrupt` adjective, `corruption` noun, `coup` noun, `cult` adjective, `cult` noun) remain excluded pending second-pass semantic QA.
- **Exact next data action:** continue authoritative extraction immediately after `flesh` noun in another large source-backed batch; isolate ambiguous rows instead of blocking later extraction.

### Recall Study Scope / Workspace
- Durable scope IDs: `all`, `a1`, `a2`, `b1`, `b2`, `c1`; labels: `All Oxford 5000`, `A1`, `A2`, `B1`, `B2`, `C1`.
- Independent scope assignments, active deck, current card and remaining shuffle progress are implemented. Legacy Recall state migrates into `All`; level scopes initialize eligible entries to core deck 1.
- Native keyboard/NVDA Study Scope ComboBox is implemented. Existing `Ctrl+1..5` / `Alt+1..5` operate inside the current scope. Stable scope actions are rebindable and default unassigned.
- Newly activated C1 rows enter `All` and `C1` deterministically without changing existing All-scope assignments.

### British offline audio
- Oxford 3000 technical generation: **3,308/3,308**.
- Targeted Oxford 3000 QA queue: 36 numbered/sense-marker candidates; 19 deterministic `ready`, 17 heteronym/sense-sensitive `review`; acronym/listening candidates remain separate. The review rows are not silently generated as guessed replacements.
- Oxford 5000 MP3 coverage before the current batch: **0/606 activated additions**.
- A new fail-closed `--export-oxford5000-audio-source` CLI path now exports exactly `ReviewedOxford5000Bootstrap.ExpectedCanonicalRows` stable verified additions directly from the runtime ledger. This removes the previous duplicated/manual audio-source TSV risk.
- The Linux audio workflow now builds that exporter only for `source=oxford5000`, verifies exported row count against the runtime constant, then feeds the existing Kokoro/Misaki British generator.
- **A single 606-entry British batch has been requested** with `bf_emma`/`bm_george`, speed 1.0 and 24 kHz MP3. Completion/integrity is pending the workflow artifact gate; do not count it as audio coverage until manifest/file/SHA-256 validation is green.
- Runtime remains offline and independent of Kokoro/Python/API/network.

### Hotkey / F1 truth audit
- Shared `ShortcutFormatter` is the canonical display path for human-readable forms such as `Ctrl+Shift+B` and `Ctrl+Alt+F8` in F1/settings/capture UI.
- Recall registry contract: 11 Recall commands + 6 scope actions + 10 five-core-deck switch/move actions = **27** actions before user-created Recall decks; each user deck adds two stable actions.
- Scope actions start unassigned. `Ctrl+S` explicit save and `Ctrl+Shift+A` bulk add are regression-asserted.
- Spelling delete remains **Ctrl+Shift+Delete**, not Ctrl+Alt+Delete.

### Emergency blockers
- **No user-input blocker.**
- Full official Oxford 5000 row-level extraction remains incomplete: 606 source-reviewed runtime additions are committed, but the complete official addition inventory is not finished.
- The current 606-addition British audio batch is running/pending artifact validation; audio coverage must remain 0/606 in release accounting until the workflow is green.
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