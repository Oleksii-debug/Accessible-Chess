# WordDeck development checkpoint

Last updated: 2026-08-19
Branch: `worddeck-bootstrap` only. Never develop WordDeck on `main`.

## Emergency Oxford 5000 milestone

### Oxford lexical data
- Runtime production bridge remains **3,682 rows = 3,308 unchanged Oxford 3000 baseline rows + 374 verified canonical B2/C1 Oxford 5000 rows**. Existing Oxford 3000 IDs/progress remain unchanged and the durable dictionary ID remains `oxford-3000-en-uk` for lossless migration.
- Five consecutive post-bridge C1 slices remain runtime-eligible: **43/43** rows `boast` verb C1 through `chamber` noun C1, **29/29** rows `chaos` noun C1 through `colonial` adjective C1, **29/29** rows `columnist` noun C1 through `compute` verb C1, **29/29** rows `conceal` verb C1 through `constitution` noun C1, and **29/29** rows `constitutional` adjective C1 through `correlation` noun C1.
- A new source-backed staging slice now contains **29 additional verified C1 rows** in `QA/oxford5000_source_after_correlation_c1_0001_0029.tsv`. It advances verified source/translation work from `correspond` verb C1 through `dam` noun C1 while deliberately deferring five semantically broader rows (`corrupt` adjective, `corruption` noun, `coup` noun, `cult` adjective, `cult` noun) for separate second-pass QA instead of guessing or blocking later extraction.
- The new 29-row staging slice was checked against the official Oxford 3000/5000 list on 2026-08-19 for exact headword/POS/CEFR membership. Higher-risk entries including `correspond`, `correspondence`, `counter`, `courtesy`, `craft` verb and `crude` adjective received targeted Oxford Advanced Learner's Dictionary sense checks before activation in the staging ledger. Distinct POS rows remain distinct stable lexical identities.
- Oxford 5000 contains Oxford 3000 plus about 2,000 additional B2-C1 words; no Oxford C2 scope is invented.
- Runtime recomputes stable IDs from `source + POS + CEFR` and fails closed on mismatch, blank translation, non-verified status, duplicate lexical identity or unsupported level.
- Current **runtime-safe** frontier remains `correlation` noun C1 until the new staged 29-row file is wired through the canonical bootstrap and grouped regression gate. Current **source-backed staging** frontier reaches `dam` noun C1.
- B2-exclusive membership beyond the existing audited bridge still requires Oxford 5000-specific membership/source metadata rather than inference from CEFR alone.
- Exact next data action: integrate the new 29-row staging slice into the canonical runtime bridge, add regression assertions/counts, then continue the next large source-backed C1 batch after `dam`; keep the five deferred semantic rows isolated for targeted second-pass QA.

### Recall Study Scope / Workspace
- Durable scope IDs remain exactly `all`, `a1`, `a2`, `b1`, `b2`, `c1`; display labels remain `All Oxford 5000`, `A1`, `A2`, `B1`, `B2`, `C1`.
- Scope storage persists independent deck assignments, active deck, current card and remaining shuffle progress per dictionary/scope. Legacy Recall assignments/current card/active deck migrate losslessly into `All`; level scopes initialize eligible entries to core deck 1.
- Native keyboard/NVDA Study Scope ComboBox remains implemented. Existing `Ctrl+1..5` / `Alt+1..5` operate only inside the current scope. Stable scope actions are rebindable and default unassigned.
- All newly activated C1 rows automatically participate in `All Oxford 5000` and `C1` through the existing level filter; initialization does not alter existing All-scope assignments.

### British offline audio
- Existing Oxford 3000 technical generation remains **3,308/3,308** stable entries.
- Targeted pronunciation QA remains 36 numbered/sense-marker candidates with 19 deterministic `ready` replacements and 17 heteronym/sense-sensitive `review` records; uppercase/acronym listening candidates remain separate.
- Canonical runtime Oxford 5000 additions remain **374 runtime-stable lexical IDs**; the newly staged 29 rows are not counted as runtime/audio targets until canonical integration passes.
- **Oxford 5000 addition MP3 coverage remains 0/374 generated files at this checkpoint.** Exact next audio action after canonical integration: generate one meaningful British batch for activated additions with stable-ID manifest and SHA-256 integrity, then append later verified rows only after lexical QA threshold. Do not wholesale-regenerate Oxford 3000.
- Kokoro/Misaki remains development-only; WordDeck runtime stays offline and has no Python/API/network dependency.

### Hotkey / F1 truth audit
- Shared `ShortcutFormatter` remains the canonical display path (`Ctrl+Shift+B`, `Ctrl+Alt+...`) for F1/settings/capture UI.
- Current Recall registry contract remains 11 Recall commands + 6 stable scope actions + 10 five-core-deck switch/move actions = **27** actions before user-created Recall decks; a user deck adds exactly two stable actions.
- Scope actions start unassigned; conflict and unsafe-key checks remain covered. `Ctrl+S` explicit save and `Ctrl+Shift+A` bulk add are asserted from code.
- Spelling delete remains **Ctrl+Shift+Delete**, not Ctrl+Alt+Delete; help/documentation must continue to reflect executable truth.

### Emergency blockers
- **No user-input blocker.**
- Full-data blocker: complete official Oxford 5000 row-level extraction is still incomplete. Runtime-safe verified additions remain **374**, with **29 additional verified rows staged** for the next grouped runtime integration.
- Second-pass queue: five rows skipped from this batch because their semantic range warrants separate targeted review rather than broad gloss activation.
- Audio blocker: Oxford 5000 addition MP3 generation has not started; targeted Oxford 3000 pronunciation replacements are not release-complete.
- Verification discipline: the new source-backed 29-row staging commit is not called a user-testable beta until it is wired into the canonical bridge and a grouped Windows build, self-tests, self-contained publish and published-EXE self-test are confirmed green.

## Parallel lanes (non-blocking)
- Core Recall/Spelling/Sentence persisted state remains preserved. No Grammar/Story/speech-recognition/My Corrector/future-module work started.
- Sentence Coach/SQLite receives no majority effort while the emergency Oxford deliverable is incomplete.
- Oxford 3000 semantic QA remains independent and does not block Oxford 5000 extraction/audio/scope delivery.

## Safety / release discipline
- `main` remains untouched.
- Existing Oxford 3000 stable IDs/progress remain regression-protected as the unchanged first 3,308 rows of the candidate package.
- No secrets, runtime network requirement, Python runtime or Kokoro runtime were added.
- Only verified Oxford source rows are embedded; pending/second-pass rows remain QA-only.
- No beta is sent automatically.