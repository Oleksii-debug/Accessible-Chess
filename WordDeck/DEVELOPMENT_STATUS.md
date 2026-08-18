# WordDeck development checkpoint

Last updated: 2026-08-18
Branch: `worddeck-bootstrap` only. Never develop WordDeck on `main`.

## Emergency Oxford 5000 milestone

### Oxford lexical data
- Runtime production bridge remains **3,523 rows = 3,308 unchanged Oxford 3000 baseline rows + 215 verified canonical B2/C1 Oxford 5000 rows**, ending at noun `blow` B2. Existing Oxford 3000 IDs/progress are preserved and the durable dictionary ID remains `oxford-3000-en-uk` for lossless migration.
- `ReviewedOxford5000Bootstrap` remains fail-closed: only `verified` reviewed rows enter runtime; merged POS/CEFR groups require explicit split rows; blanks, duplicate lexical identities, stable-ID collisions, unsupported levels and missing audited rows fail closed.
- **New source-backed extraction progress this run:** staged `QA/oxford5000_source_after_blow_c1_0001_0043.tsv` with **43 additional official C1 lexical rows after `blow`**, from `boast` verb C1 through `chamber` noun C1. Stable canonical IDs are already assigned using the production headword+POS+CEFR SHA-256 identity contract.
- These 43 rows are deliberately `pending_translation_qa` and are **not embedded or shipped yet**. This is intentional fail-closed behavior: no blank, guessed or unreviewed Ukrainian translations enter a user build.
- The C1-only extraction slice is authoritative without needing Oxford 3000 subtraction: Oxford documents Oxford 3000 as A1-B2 and Oxford 5000 additions as B2-C1, so combined-list C1 rows are necessarily Oxford 5000-exclusive. B2 additions after `blow` still require exclusive-list/source metadata subtraction and remain to be extracted separately.
- Fresh Oxford verification on 2026-08-18: Oxford Learner's Dictionaries states Oxford 5000 = Oxford 3000 plus about 2,000 additional B2-C1 words; the official web word list exposes headword, POS and CEFR. No Oxford C2 subset is to be invented.
- Exact next data action: translate/second-pass the new 43-row C1 slice in a source-safe batch while continuing extraction beyond `chamber`, and separately recover B2-exclusive membership from official `data-ox3000`/`data-ox5000` metadata rather than inferring it from CEFR alone.

### Recall Study Scope / Workspace
- Durable scope IDs remain exactly `all`, `a1`, `a2`, `b1`, `b2`, `c1`; display labels are `All Oxford 5000`, `A1`, `A2`, `B1`, `B2`, `C1`.
- Scope storage persists independent deck assignments, active deck, current card and remaining shuffle progress per dictionary/scope. Legacy Recall assignments/current card/active deck migrate losslessly into `All`; level scopes initialize eligible entries to core deck 1.
- Native keyboard/NVDA Study Scope ComboBox is implemented. Existing `Ctrl+1..5` / `Alt+1..5` remain current-scope deck switch/move actions. Stable scope actions are rebindable and default unassigned.
- Current runtime scope coverage includes the 215 activated additions; the newly staged 43 C1 rows will enter C1/All only after translation QA and runtime activation.

### British offline audio
- Existing Oxford 3000 technical generation remains **3,308/3,308** stable entries.
- Targeted pronunciation QA remains 36 numbered/sense-marker candidates with 19 deterministic `ready` replacements and 17 heteronym/sense-sensitive `review` records; uppercase/acronym listening candidates remain separate.
- Canonical Oxford 5000 additions have stable production IDs for the first 215 runtime rows; the newly staged 43 C1 rows also already have stable canonical IDs, but remain translation-QA pending and therefore are not audio-release eligible yet.
- **Canonical Oxford 5000 addition audio remains 0 generated files** at this checkpoint. Exact next audio action: generate British MP3 for the 215 activated rows as one meaningful batch, with stable-ID manifest and SHA-256 integrity, then add later rows only after they cross lexical QA threshold. No wholesale Oxford 3000 regeneration.
- Kokoro/Misaki remains development-only; WordDeck runtime stays offline and has no Python/API/network dependency.

### Hotkey / F1 truth audit
- Shared `ShortcutFormatter` remains the canonical display path (`Ctrl+Shift+B`, `Ctrl+Alt+...`) for F1/settings/capture UI.
- Current Recall registry contract remains 11 Recall commands + 6 stable scope actions + 10 five-core-deck switch/move actions = **27** actions before user-created Recall decks; a user deck adds exactly two stable actions.
- Scope actions start unassigned; conflict and unsafe-key checks remain tested. `Ctrl+S` explicit save and `Ctrl+Shift+A` bulk add are asserted from code.
- Spelling delete remains **Ctrl+Shift+Delete**, not Ctrl+Alt+Delete; documentation/help must continue to reflect code truth.

### Emergency blockers
- **No user-input blocker.**
- Full-data blocker: complete official Oxford 5000 row-level extraction is still incomplete. Runtime-safe verified coverage remains 215 additions; 43 further C1 rows are now source-extracted but translation-QA pending.
- Audio blocker: Oxford 5000 addition MP3 generation has not started; targeted Oxford 3000 pronunciation replacements are not release-complete.
- Verification discipline: do not call any exact head a testable beta until grouped Windows build, self-tests, self-contained publish and published-EXE self-test are green for that head.

## Parallel lanes (non-blocking)
- Core Recall/Spelling/Sentence persisted state remains preserved. No Grammar/Story/speech-recognition/My Corrector/future-module work started.
- Sentence Coach/SQLite receives no majority effort while the emergency Oxford deliverable is incomplete.
- Oxford 3000 semantic QA remains independent and does not block Oxford 5000 extraction/audio/scope delivery.

## Safety / release discipline
- `main` remains untouched.
- Existing Oxford 3000 stable IDs/progress remain regression-protected as the unchanged first 3,308 rows of the candidate package.
- No secrets, runtime network requirement, Python runtime or Kokoro runtime were added.
- Pending Oxford source rows are staged as QA data only and are intentionally excluded from `WordDeck.csproj` embedded resources until translation QA passes.
- No beta is sent automatically.
