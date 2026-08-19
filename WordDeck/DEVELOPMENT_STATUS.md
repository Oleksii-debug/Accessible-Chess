# WordDeck development checkpoint

Last updated: 2026-08-19
Branch: `worddeck-bootstrap` only. Never develop WordDeck on `main`.

## Emergency Oxford 5000 milestone

### Oxford lexical data
- Runtime production bridge remains **3,798 rows = 3,308 unchanged Oxford 3000 baseline rows + 490 verified canonical B2/C1 Oxford 5000 rows**. Existing Oxford 3000 IDs/progress remain unchanged; durable dictionary ID remains `oxford-3000-en-uk` for lossless migration.
- Three authoritative source-backed batches are now staged and verified for the next grouped activation: **29 C1 lexical rows from `donor` through `embarrassment`**, **29 C1 lexical rows from `embassy` through `equality`**, plus **29 C1 lexical rows after `equality` from `equation` through `explosive` (adjective)**. The batches preserve explicit POS distinctions, including `ease` noun/verb and the newly staged `excess` adjective/noun split, with deterministic SHA-256 stable IDs.
- Runtime-safe/source-reviewed Oxford 5000 additions are therefore **490 active + 87 newly verified staged = 577 source-checked additions available for the next grouped activation**. The 87 staged rows are deliberately not counted as runtime-active until bootstrap/self-tests and one grouped Windows gate verify the activation checkpoint.
- Oxford official list confirmation for the new staged span after `equality` was rechecked on 2026-08-19 against the official Oxford 3000/5000 list. Semantically broader rows such as `establishment`, `excess` adjective/noun, `exclusive`, `execute`, `execution`, `exert`, `exit`, `expire`, `exploitation` and `explosive` adjective were additionally checked against their current OALD entries rather than inferred from spelling alone.
- Activated and staged source files remain fail-closed: every runtime row must be `verified`, have nonblank Ukrainian translation, supported B2/C1 CEFR, unique lexical identity and a stable ID recomputed from lowercase `source + U+001F + POS + U+001F + CEFR` using SHA-256.
- Earlier POS splits for `dispute` noun/verb and `distress` noun/verb remain distinct stable lexical entries; no POS/sense collapse was introduced.
- Five semantically broader earlier C-region rows (`corrupt` adjective, `corruption` noun, `coup` noun, `cult` adjective, `cult` noun) remain excluded pending second-pass semantic QA.
- Oxford 5000 is Oxford 3000 plus additional B2-C1 vocabulary; no Oxford C2 scope is invented.
- Runtime canonicalization remains fail-closed on stable-ID mismatch, blank translation, non-verified status, duplicate lexical identity or unsupported level.
- **Exact next data action:** continue authoritative extraction immediately after `explosive` adjective in another large verified batch if time permits; then activate the accumulated 87+ staged rows in one bootstrap/self-test/Windows checkpoint rather than spending CI minutes on every 29-row slice.

### Recall Study Scope / Workspace
- Durable scope IDs: `all`, `a1`, `a2`, `b1`, `b2`, `c1`; labels: `All Oxford 5000`, `A1`, `A2`, `B1`, `B2`, `C1`.
- Independent scope assignments, active deck, current card and remaining shuffle progress are implemented. Legacy Recall state migrates into `All`; level scopes initialize eligible entries to core deck 1.
- Native keyboard/NVDA Study Scope ComboBox is implemented. Existing `Ctrl+1..5` / `Alt+1..5` operate inside the current scope. Stable scope actions are rebindable and default unassigned.
- Newly activated C1 rows enter `All` and `C1` deterministically when activated without changing existing All-scope assignments.

### British offline audio
- Oxford 3000 technical generation: **3,308/3,308**.
- Targeted Oxford 3000 QA queue: 36 numbered/sense-marker candidates; 19 deterministic `ready`, 17 heteronym/sense-sensitive `review`; acronym/listening candidates remain separate.
- Oxford 5000 MP3 coverage remains **0/490 runtime additions**; all **87 newly staged rows** also still need generation. This is a release blocker for the emergency final milestone.
- **Exact next audio action:** generate one coherent British batch for the grouped activated Oxford 5000 set with stable-ID manifest + SHA-256 integrity, while keeping Kokoro/Misaki development-only and runtime fully offline.

### Hotkey / F1 truth audit
- Shared `ShortcutFormatter` is the canonical display path for human-readable forms such as `Ctrl+Shift+B` and `Ctrl+Alt+F8` in F1/settings/capture UI.
- Recall registry contract: 11 Recall commands + 6 scope actions + 10 five-core-deck switch/move actions = **27** actions before user-created Recall decks; each user deck adds two stable actions.
- Scope actions start unassigned. `Ctrl+S` explicit save and `Ctrl+Shift+A` bulk add are regression-asserted.
- Spelling delete remains **Ctrl+Shift+Delete**, not Ctrl+Alt+Delete.

### Emergency blockers
- **No user-input blocker.**
- Full official Oxford 5000 row-level extraction remains incomplete: 490 runtime-active additions plus 87 newly verified staged additions.
- Oxford 5000 addition MP3 generation has not started; targeted Oxford 3000 pronunciation replacements are not release-complete.
- The 87 new rows are intentionally staged without an expensive Windows gate; they will be activated in a larger coherent checkpoint to conserve CI minutes.

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
