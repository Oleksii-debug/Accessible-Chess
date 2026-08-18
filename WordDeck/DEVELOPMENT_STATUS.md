# WordDeck development checkpoint

Last updated: 2026-08-18
Branch: `worddeck-bootstrap` only. Never develop WordDeck on `main`.

## Emergency Oxford 5000 milestone

### Oxford lexical data
- Runtime production bridge is now **3,595 rows = 3,308 unchanged Oxford 3000 baseline rows + 287 verified canonical B2/C1 Oxford 5000 rows**. Existing Oxford 3000 IDs/progress remain unchanged and the durable dictionary ID remains `oxford-3000-en-uk` for lossless migration.
- Both newly source-backed C1 slices are now runtime-eligible: **43/43** rows `boast` verb C1 through `chamber` noun C1 and **29/29** rows `chaos` noun C1 through `colonial` adjective C1 passed translation QA. POS, CEFR and stable IDs remain source-derived; runtime recomputes stable IDs from `source + POS + CEFR` and fails closed on mismatch, blank translation, non-verified status, duplicate lexical identity or unsupported level.
- Fresh official Oxford verification on 2026-08-18 confirms Oxford 5000 contains Oxford 3000 plus about 2,000 additional B2-C1 words; no Oxford C2 scope is invented.
- Current source-backed and runtime-safe verified frontier reaches `colonial` adjective C1. B2-exclusive membership beyond the existing audited bridge still requires Oxford 5000-specific membership/source metadata rather than inference from CEFR alone.
- Exact next data action: continue large C1 extraction/translation batches beyond `colonial` while continuing the separate B2-exclusive extraction path from official Oxford 5000 membership metadata.

### Recall Study Scope / Workspace
- Durable scope IDs remain exactly `all`, `a1`, `a2`, `b1`, `b2`, `c1`; display labels remain `All Oxford 5000`, `A1`, `A2`, `B1`, `B2`, `C1`.
- Scope storage persists independent deck assignments, active deck, current card and remaining shuffle progress per dictionary/scope. Legacy Recall assignments/current card/active deck migrate losslessly into `All`; level scopes initialize eligible entries to core deck 1.
- Native keyboard/NVDA Study Scope ComboBox remains implemented. Existing `Ctrl+1..5` / `Alt+1..5` operate only inside the current scope. Stable scope actions are rebindable and default unassigned.
- All **72 newly activated C1 rows** automatically participate in `All Oxford 5000` and `C1` through the existing level filter; initialization does not alter existing All-scope assignments.

### British offline audio
- Existing Oxford 3000 technical generation remains **3,308/3,308** stable entries.
- Targeted pronunciation QA remains 36 numbered/sense-marker candidates with 19 deterministic `ready` replacements and 17 heteronym/sense-sensitive `review` records; uppercase/acronym listening candidates remain separate.
- Canonical Oxford 5000 additions now have **287 runtime-stable lexical IDs**.
- **Oxford 5000 addition MP3 coverage remains 0/287 generated files at this checkpoint.** Exact next audio action: generate one meaningful British batch for the 287 activated rows with stable-ID manifest and SHA-256 integrity, then append later verified rows only after lexical QA threshold. Do not wholesale-regenerate Oxford 3000.
- Kokoro/Misaki remains development-only; WordDeck runtime stays offline and has no Python/API/network dependency.

### Hotkey / F1 truth audit
- Shared `ShortcutFormatter` remains the canonical display path (`Ctrl+Shift+B`, `Ctrl+Alt+...`) for F1/settings/capture UI.
- Current Recall registry contract remains 11 Recall commands + 6 stable scope actions + 10 five-core-deck switch/move actions = **27** actions before user-created Recall decks; a user deck adds exactly two stable actions.
- Scope actions start unassigned; conflict and unsafe-key checks remain covered. `Ctrl+S` explicit save and `Ctrl+Shift+A` bulk add are asserted from code.
- Spelling delete remains **Ctrl+Shift+Delete**, not Ctrl+Alt+Delete; help/documentation must continue to reflect executable truth.

### Emergency blockers
- **No user-input blocker.**
- Full-data blocker: complete official Oxford 5000 row-level extraction is still incomplete. Runtime-safe verified additions increased from 215 at run start to **287**.
- Audio blocker: Oxford 5000 addition MP3 generation has not started; targeted Oxford 3000 pronunciation replacements are not release-complete.
- Verification discipline: do not call this exact head a testable beta until grouped Windows build, self-tests, self-contained publish and published-EXE self-test are green.

## Parallel lanes (non-blocking)
- Core Recall/Spelling/Sentence persisted state remains preserved. No Grammar/Story/speech-recognition/My Corrector/future-module work started.
- Sentence Coach/SQLite receives no majority effort while the emergency Oxford deliverable is incomplete.
- Oxford 3000 semantic QA remains independent and does not block Oxford 5000 extraction/audio/scope delivery.

## Safety / release discipline
- `main` remains untouched.
- Existing Oxford 3000 stable IDs/progress remain regression-protected as the unchanged first 3,308 rows of the candidate package.
- No secrets, runtime network requirement, Python runtime or Kokoro runtime were added.
- Only verified Oxford source rows are embedded; pending rows remain QA-only.
- No beta is sent automatically.
