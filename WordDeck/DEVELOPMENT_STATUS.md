# WordDeck development checkpoint

Last updated: 2026-08-18
Branch: `worddeck-bootstrap` only. Never develop WordDeck on `main`.

## Emergency Oxford 5000 milestone

### Oxford lexical data
- Embedded production dictionary remains the verified Oxford 3000 baseline: 3,308 lexical rows, A1-B2. Do not claim Oxford 5000 complete yet.
- Oxford 5000 additions 0001-0100 were previously translated/reviewed; staged second-pass 0101-0140 is source-checked with 0101-0120 and 0121-0140 validation slices in grouped CI.
- Remaining extraction/QA is still incomplete; C1 must come only from authoritative Oxford 5000 additions. No Oxford C2 scope or invented C2 entries.
- Exact next data action: continue source-backed review from 0141 onward in large fail-closed batches, then promote only rows with nonblank, non-guessed translations and resolved POS/sense/CEFR metadata.

### Recall Study Scope / Workspace
- Added durable scope IDs exactly: `all`, `a1`, `a2`, `b1`, `b2`, `c1`; display labels are `All Oxford 5000`, `A1`, `A2`, `B1`, `B2`, `C1`.
- Added persistent per-dictionary/per-scope Recall state model with independent deck assignments, active deck and current card.
- Added migration service: legacy Recall assignments/current card/active deck are copied losslessly into `All`; level scopes include only exact CEFR rows and initialize eligible entries deterministically to core deck 1.
- Moving an entry in a level scope cannot alter `All` or another level scope. `All` continues synchronizing legacy Recall fields for backwards compatibility during the transition.
- Existing custom deck definitions remain untouched and valid destinations; no destructive migration was introduced.
- Added stable rebindable actions `recall_scope_<scopeId>` for all six scopes. They deliberately default to `Unassigned` to avoid shortcut conflicts.
- Added regression test source covering legacy-to-All migration, level filtering, independent assignments, ineligible-entry rejection, six dynamic scope actions and shortcut formatting. The test source exists but still needs wiring into the aggregate self-test entry point before this vertical slice is considered verified.
- UI selector is not implemented yet; therefore no user-testable scope build is claimed.
- Exact next scope action: wire scope tests into `--self-test`, normalize nested scope dictionaries on JSON reload, then integrate `RecallStudyScopeService` into `MainForm` with a native keyboard/NVDA-accessible ComboBox, scope-specific counts/current-card restore and scope-action dispatch.

### British offline audio
- Existing Oxford 3000 technical generation remains 3,308/3,308 stable entries.
- Targeted pronunciation QA remains artifact-level work: source resolutions/override ledger exist for heteronym/sense-marker/uppercase candidates; do not regenerate the whole Oxford 3000 pack.
- Exact next audio action: validate the targeted replacement artifact by stable ID/hash, merge only verified replacements, then generate audio only for newly verified Oxford 5000 additions.

### Hotkey / F1 truth audit
- Shortcut display is now canonicalized explicitly as `Ctrl+Shift+B`, `Ctrl+Alt+...`, etc., rather than relying on `Keys.ToString()`/converter ordering.
- Scope actions are present in the shared `ShortcutManager`, so once the UI dispatch is wired they will automatically appear in shortcut settings/help through the common definitions path.
- Current Spelling delete default remains `Ctrl+Shift+Delete`; regression test source asserts that display text exactly.
- Exact next action: verify every ShortcutSettings/F1/hint call site uses `ShortcutFormatter.Format`, wire scope actions to MainForm dispatch, and run the grouped Windows gate at the next coherent checkpoint.

### Emergency blockers
- No user-input blocker.
- Release blocker: full authoritative Oxford 5000 lexical inventory/translation QA is incomplete.
- Vertical-slice blocker: MainForm has not yet switched Recall storage/navigation to the new scope service and has no Study Scope selector.
- Audio blocker: targeted Oxford 3000 replacement artifact still needs final manifest/hash inspection; Oxford 5000 additions need audio after lexical verification.

## Parallel lanes (non-blocking)
- Core Recall/Spelling/Sentence data remain preserved; no Grammar/Story/speech-recognition/future-module work started.
- Sentence Coach low-memory SQLite path remains available but receives no majority effort while the emergency Oxford deliverable is incomplete.
- Production SentencePack release packaging still needs its SQLite companion included and validated; this is explicitly secondary to Oxford 5000 + Recall scopes + audio.
- Oxford 3000 semantic QA may continue independently but must not block the emergency deliverable.

## Safety / release discipline
- `main` remains untouched.
- No secrets, API keys, network runtime requirement, Python runtime or Kokoro runtime were added.
- No routine beta artifact should be sent until a coherent Windows x64 build proves the Recall scope selector and independent assignments end-to-end. Real NVDA compatibility is not claimed until user testing.
