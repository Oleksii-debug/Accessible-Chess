# WordDeck development checkpoint

Last updated: 2026-08-19
Branch: `worddeck-bootstrap` only. Never develop WordDeck on `main`.

## Emergency Oxford 5000 milestone

### Oxford lexical data
- Runtime production bridge remains **3,740 rows = 3,308 unchanged Oxford 3000 baseline rows + 432 verified canonical B2/C1 Oxford 5000 rows**. Existing Oxford 3000 IDs/progress remain unchanged; durable dictionary ID remains `oxford-3000-en-uk` for lossless migration.
- Two consecutive source-reviewed but not-yet-runtime-activated C1 slices are now staged: **29 rows after `deployment` through `directory`**, and **29 rows after `directory` through `dominance`**. Source-reviewed/staged Oxford 5000 additions therefore total **490 = 432 runtime + 58 staged**.
- Newest staged slice: `QA/oxford5000_source_after_directory_c1_0001_0029.tsv`. It preserves POS splits for `dispute` noun/verb and `distress` noun/verb; all 29 stable IDs were recomputed from lowercase `source + U+001F + POS + U+001F + CEFR` using SHA-256 and checked against the existing lexical-ID contract.
- Official membership/POS/CEFR was checked against Oxford Learner's Dictionaries on **2026-08-19**. Only C1 rows were advanced in this slice; intervening B2 rows remain for their dedicated source-backed extraction path rather than being inferred or silently skipped from the final inventory.
- Five semantically broader earlier C-region rows (`corrupt` adjective, `corruption` noun, `coup` noun, `cult` adjective, `cult` noun) remain excluded pending second-pass semantic QA.
- Oxford 5000 is Oxford 3000 plus additional B2-C1 vocabulary; no Oxford C2 scope is invented.
- Runtime canonicalization remains fail-closed on stable-ID mismatch, blank translation, non-verified status, duplicate lexical identity or unsupported level.
- **Exact next data action:** activate both 29-row staged slices together (58 rows) in `ReviewedOxford5000Bootstrap`/embedded resources, update end-of-ledger regression assertions, then run one grouped Windows gate. Continue source extraction after `dominance` in parallel; do not spend CI on a staging-only commit.

### Recall Study Scope / Workspace
- Durable scope IDs: `all`, `a1`, `a2`, `b1`, `b2`, `c1`; labels: `All Oxford 5000`, `A1`, `A2`, `B1`, `B2`, `C1`.
- Independent scope assignments, active deck, current card and remaining shuffle progress are implemented. Legacy Recall state migrates into `All`; level scopes initialize eligible entries to core deck 1.
- Native keyboard/NVDA Study Scope ComboBox is implemented. Existing `Ctrl+1..5` / `Alt+1..5` operate inside the current scope. Stable scope actions are rebindable and default unassigned.
- Newly activated C1 rows will automatically enter `All` and `C1` without changing existing All-scope assignments.

### British offline audio
- Oxford 3000 technical generation: **3,308/3,308**.
- Targeted Oxford 3000 QA queue: 36 numbered/sense-marker candidates; 19 deterministic `ready`, 17 heteronym/sense-sensitive `review`; acronym/listening candidates remain separate.
- Oxford 5000 MP3 coverage: **0/432 runtime entries; 0/490 including staged entries**. This is a release blocker for the emergency final milestone.
- **Exact next audio action:** generate one coherent British batch for activated Oxford 5000 additions with stable-ID manifest + SHA-256 integrity, while keeping Kokoro/Misaki development-only and runtime fully offline.

### Hotkey / F1 truth audit
- Shared `ShortcutFormatter` is the canonical display path for human-readable forms such as `Ctrl+Shift+B` and `Ctrl+Alt+F8` in F1/settings/capture UI.
- Recall registry contract: 11 Recall commands + 6 scope actions + 10 five-core-deck switch/move actions = **27** actions before user-created Recall decks; each user deck adds two stable actions.
- Scope actions start unassigned. `Ctrl+S` explicit save and `Ctrl+Shift+A` bulk add are regression-asserted.
- Spelling delete remains **Ctrl+Shift+Delete**, not Ctrl+Alt+Delete.

### Emergency blockers
- **No user-input blocker.**
- Full official Oxford 5000 row-level extraction remains incomplete: 432 runtime-safe additions, 490 source-reviewed/staged additions.
- Oxford 5000 addition MP3 generation has not started; targeted Oxford 3000 pronunciation replacements are not release-complete.
- No testable emergency beta is declared until the next grouped activation passes bootstrap/self-tests/self-contained publish/published-EXE validation.

## Parallel lanes (non-blocking)
- Core Recall/Spelling/Sentence persisted state remains preserved. No Grammar/Story/speech-recognition/My Corrector work started.
- Sentence Coach/SQLite received no majority effort while emergency Oxford work remains incomplete.
- Oxford 3000 semantic QA remains independent and does not block Oxford 5000 extraction/audio/scope delivery.

## Safety / release discipline
- `main` remains untouched.
- Existing Oxford 3000 stable IDs/progress remain regression-protected as the unchanged first 3,308 rows.
- No secrets, runtime network requirement, Python runtime or Kokoro runtime were added.
- Only source-checked rows are staged; ambiguous/pending rows remain QA-only.
- No beta is sent automatically.