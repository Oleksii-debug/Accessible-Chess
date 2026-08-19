# WordDeck development checkpoint

Last updated: 2026-08-19
Branch: `worddeck-bootstrap` only. Never develop WordDeck on `main`.

## Emergency Oxford 5000 milestone

### Oxford lexical data
- Current branch runtime target is **4,290 dictionary rows = 3,308 unchanged Oxford 3000 baseline rows + 982 verified/activated Oxford 5000 additions**. Existing Oxford 3000 IDs/progress remain unchanged; durable dictionary ID remains `oxford-3000-en-uk` for lossless migration.
- Authoritative membership-preserving reconciliation is now established: **2,138 Oxford 5000-exclusive lexical rows total**. At the current runtime checkpoint **982 are activated and 1,156 are exactly unaccounted/not yet integrated**. Do not report this tail as UNKNOWN and do not infer completion from the activated count.
- Newly activated source-backed slice: **29 C1 lexical rows from `operational` adjective through `passing` noun** in `QA/oxford5000_source_after_offspring_verified_c1_0001_0029.tsv`.
- Previous activated slices include `myth` noun → `offender` noun (29 B2/C1 rows), `methodology` noun → `mutual` adjective (29 rows), and `namely` adverb → `offspring` noun (28 C1 rows).
- `ReviewedOxford5000Bootstrap.ExpectedCanonicalRows` is **982** and activation remains fail-closed: only `status=verified`, nonblank Ukrainian translation, valid B2/C1 and exact stable ID are admitted.
- `tools/fetch_oxford5000_official_html.py`, `tools/validate_oxford5000_official_inventory.py` and `tools/validate_oxford5000_runtime_ledger.py` provide the reproducible authoritative inventory/reconciliation path. Windows CI runs full `--official-html` reconciliation and emits the exact unaccounted ledger.
- `tools/validate_oxford5000_automation_handoff.py` is the canonical deterministic Data Factory → Content QA → Work integration validator. It validates current exact-unaccounted membership, stable IDs, run linkage, full QA coverage and PASS-only integration.
- `tools/validate_oxford5000_handoff_provenance.py` adds strict TSV shape validation plus SHA-256/byte-size evidence for the authoritative unaccounted ledger, Data Factory batch and Content QA batch without performing harvesting or linguistic judgement.

### Stage 1 automation ownership
- Broad Oxford candidate harvesting belongs to `WORDDECK AUTO-DATA-FACTORY`, which writes append-only outputs only to Drive `05_AUTO_DATA_FACTORY`.
- First-line linguistic/source/translation QA belongs to `WORDDECK AUTO-CONTENT-QA`, which writes append-only outputs only to Drive `06_AUTO_CONTENT_QA`.
- Work is the sole canonical GitHub integrator. Work must consume only QA-qualified broad batches and must not fabricate automation output or duplicate broad harvesting/first-line linguistic QA when those folders are empty.
- Work may perform targeted repairs/reconciliation and deterministic integration, provenance, corpus-accounting and CI hardening.
- At the latest Work inspection on 2026-08-19, both automation output folders were still empty, so no new broad lexical batch was eligible for integration.

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
- Current runtime lexical target is **982 Oxford 5000 additions**. British audio for all 982 additions is not yet fully generated and independently validated, so full Oxford 5000 audio coverage is explicitly **not** claimed.
- Runtime remains offline and independent of Kokoro/Python/API/network.

### Hotkey / F1 truth audit
- Shared `ShortcutFormatter` remains the canonical display path for human-readable forms such as `Ctrl+Shift+B` and `Ctrl+Alt+F8` in F1/settings/capture UI.
- Recall registry contract remains 11 Recall commands + 6 scope actions + 10 five-core-deck switch/move actions = **27** actions before user-created Recall decks; each user deck adds two stable actions.
- Scope actions start unassigned. `Ctrl+S` explicit save and `Ctrl+Shift+A` bulk add are regression-asserted.
- Spelling delete remains **Ctrl+Shift+Delete**, not Ctrl+Alt+Delete.

### Emergency blockers / open gates
- **No user-input blocker.**
- Exact authoritative Stage 1 accounting is **2,138 total / 982 activated / 1,156 remaining**.
- A successful Windows authoritative/executable gate already exists for the 982-runtime checkpoint from the prior Work cycle; any later tooling-only checkpoint must also remain green before handoff evidence is called current.
- Broad corpus throughput is presently limited by the absence of a QA-qualified Data Factory → Content QA Drive batch; Work must not bypass that ownership contract by fabricating broad linguistic output.
- British audio for all activated Oxford 5000 additions is not yet fully verified; do not claim full Oxford 5000 audio coverage.
- Targeted Oxford 3000 pronunciation replacements remain incomplete for 17 sense-sensitive review rows; do not guess them.

### Exact next action
1. Check `05_AUTO_DATA_FACTORY` and `06_AUTO_CONTENT_QA` first.
2. When a complete QA-qualified broad batch exists, validate it against the exact current unaccounted ledger using both automation handoff and strict provenance gates, then integrate only PASS rows; preserve REJECT/BLOCKED rows fail-closed.
3. Re-run authoritative corpus reconciliation and prove that the exact remaining count decreases from 1,156 by exactly the newly integrated authoritative rows.
4. Run the Windows authoritative gate through published `WordDeck.exe --self-test` and retain run/artifact evidence for the auditor.
5. If the automation folders remain empty, continue only deterministic integration/provenance/CI hardening or targeted repair; do not substitute Work-side broad harvesting or first-line linguistic QA.

## Parallel lanes (non-blocking)
- British audio may progress for already verified unambiguous English entries, but must not replace the Stage 1 corpus objective.
- Sentence/SQLite and Oxford 3000 semantic QA remain lower priority and must not delay Stage 1.
- Core Recall/Spelling/Sentence persisted state remains preserved. No Grammar/Story/speech-recognition/My Corrector work started.

## Safety / release discipline
- `main` remains untouched.
- Existing Oxford 3000 stable IDs/progress remain regression-protected as the unchanged first 3,308 rows.
- No secrets, runtime network requirement, Python runtime or Kokoro runtime were added. Official-source network access is build/CI-only.
- Only rows satisfying authoritative membership, source/POS/CEFR, Content-QA qualification, translation QA and stable-ID gates may be runtime-activated; pending/unresolved rows remain fail-closed.
- No beta is sent automatically.
