# WordDeck development checkpoint

Last updated: 2026-08-18
Branch: `worddeck-bootstrap` only. Never develop WordDeck on `main`.

## Emergency Oxford 5000 milestone

### Oxford lexical data
- Embedded production dictionary remains the verified Oxford 3000 baseline: **3,308 lexical rows**, A1-B2. No Oxford 5000 addition is yet exposed by `DictionaryLoader` in this checkpoint; that gate remains intentional until the executable self-test is updated for the larger production package.
- The previously reviewed `ox5000-add-0001..0200` material is explicitly treated as **legacy translation-working groups**, not production lexical IDs.
- The source-structure audit found 13 merged POS groups (`abuse`, `acid`, `advocate`, `alert`, `alien`, `alike`, `amateur`, `assault`, `attribute`, `besides`, `bid`, `blast`, `blend`) plus the omitted official row `assumption` noun B2. After those corrections, the audited `abolish` through noun `blow` span is **215 lexical rows**.
- New `tools/canonicalize_oxford5000_reviewed.py` now converts exactly the 200 already-reviewed translation groups plus the verified split map into a fail-closed **215-row canonical ledger**. It requires every source translation row to be `verified`, rejects merged metadata unless an explicit split exists, restores `assumption`, rejects blank translations, duplicate lexical identities and stable-ID collisions, and refuses any level other than B2/C1.
- Canonical Oxford 5000 stable IDs are now URL- and order-independent: normalized **headword + POS + CEFR** -> SHA-256-derived `ox5000-...` ID. The official definition URL remains provenance only, so later Oxford URL routing changes cannot silently invalidate user progress.
- `tools/extract_oxford5000_official.py` uses the same lexical-ID rule and fails closed on duplicate headword/POS/CEFR identities and any invented C2 level.
- `ReviewedOxford5000Bootstrap.cs` is staged as the strict runtime bridge for those 215 rows. The five reviewed QA ledgers are embedded as build resources so the bridge can be compiled and tested without duplicating translation data. It preserves the existing dictionary ID when eventually activated so existing Oxford 3000 Recall progress can migrate losslessly into `All`.
- The runtime bridge is **not activated yet**: the old executable self-test still asserts exactly 3,308 rows. Leaving `DictionaryLoader` on the known-good baseline avoids shipping an unverified 3,523-row package merely to make the emergency slice appear finished.
- Exact next data action: make the executable Oxford self-test understand the preserved 3,308 baseline plus 215 canonical additions, activate the bridge, and require the grouped Windows build/published-EXE gate to prove **3,523 total rows** with all original IDs intact. In parallel, continue authoritative source extraction beyond `blow` in large row-preserving batches.

### Recall Study Scope / Workspace
- Durable scope IDs are exactly: `all`, `a1`, `a2`, `b1`, `b2`, `c1`; display labels are `All Oxford 5000`, `A1`, `A2`, `B1`, `B2`, `C1`.
- Scope storage persists independent deck assignments, active deck, current card and remaining shuffle progress for every dictionary/scope.
- Legacy Recall assignments/current card/active deck migrate losslessly into `All`; level scopes contain only exact CEFR rows and initialize eligible entries to core deck 1.
- Main Recall UI has a native keyboard/NVDA-accessible Study Scope ComboBox. Scope switching restores scope-specific deck/current-card/shuffle state and announces current scope + total.
- Existing `Ctrl+1..5` / `Alt+1..5` operate only inside the current scope. Stable rebindable `recall_scope_<scopeId>` actions exist for all six scopes and start unassigned.
- Custom pasted cards remain restricted to `All Oxford 5000`; existing custom-deck data remains preserved.
- Scope regression tests already cover migration, CEFR filtering, independent assignments/progress, persistence, scope actions, conflicts and shortcut formatting.
- Exact next scope action: activate the 215 canonical rows only together with the updated executable test, then prove the real B2/C1 scope paths on that production-shaped dataset.

### British offline audio
- Existing Oxford 3000 technical generation remains **3,308/3,308** stable entries.
- Pronunciation-content QA remains targeted rather than wholesale: 36 numbered/sense-marker candidates are in the override ledger, with 19 deterministic `ready` replacements and 17 heteronym/sense-sensitive `review` records; 5 uppercase/acronym candidates remain a separate listening/letter-name set.
- Oxford 5000 addition audio remains **0 canonical files generated** in this checkpoint. The important blocker has changed: canonical stable IDs now exist deterministically for the first 215 reviewed rows, so audio generation for those rows can begin after the 3,523-row executable package is green.
- Kokoro/Misaki remains development-only; WordDeck runtime stays offline with no Python/API/network dependency.
- Exact next audio action: finish/validate the targeted Oxford 3000 replacements independently, then generate British MP3 + manifest/hash entries for only the activated canonical Oxford 5000 rows.

### Hotkey / F1 truth audit
- Shared `ShortcutFormatter` renders combinations canonically (`Ctrl+Shift+B`, `Ctrl+Alt+...`) and is used by F1, shortcut settings and capture UI.
- Scope actions use stable action IDs and are rebindable/persistent.
- Spelling delete default is **Ctrl+Shift+Delete**; regression coverage asserts actual defaults and conflict handling.
- Recall help documents all six scopes, no Oxford C2, scope independence, and current-scope deck semantics.
- No known remaining user-facing `Keys.ToString()` path.

### Emergency blockers
- **No user-input blocker.**
- Full-data blocker: authoritative row-level extraction beyond noun `blow` is still incomplete; the full official Oxford 5000 cannot yet be claimed.
- Immediate vertical-slice blocker: executable tests still encode the 3,308-row baseline contract. The 215-row canonical bridge is staged but deliberately not activated until that contract is updated and a grouped Windows/published-EXE gate is green.
- Audio blocker: targeted Oxford 3000 pronunciation replacements are not release-complete; Oxford 5000 addition audio starts only after corresponding canonical rows are activated.

## Parallel lanes (non-blocking)
- Core Recall/Spelling/Sentence state remains preserved; no Grammar/Story/speech-recognition/future-module work started.
- Sentence Coach SQLite work received no majority effort in this emergency cycle.
- Oxford 3000 semantic QA remains independent and does not block Oxford 5000 extraction/audio/scope delivery.

## Safety / release discipline
- `main` remains untouched.
- Existing Oxford 3000 stable IDs/progress remain untouched. The old merged Oxford 5000 staging IDs are still not production IDs.
- No secrets, runtime network requirement, Python runtime or Kokoro runtime were added.
- Do not send a beta automatically. A beta becomes eligible only after canonical additions are activated and a coherent Windows x64 build/self-test/published-EXE gate proves the scope/state path end-to-end; real NVDA compatibility still requires user testing.
