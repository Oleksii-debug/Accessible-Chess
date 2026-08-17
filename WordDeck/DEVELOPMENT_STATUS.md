# WordDeck development checkpoint

Last updated: 2026-08-17
Branch: `worddeck-bootstrap` only. `main` is not a development target for this work.

## Regression baseline that must remain green

Recall track remains the compatibility gate: five permanent renameable core decks plus arbitrary user decks, stable deck IDs and switch/move shortcuts, random shuffle-bag navigation on both Ctrl+Left/Ctrl+Right, accessible all-deck counts, custom pasted cards, local autosave/backup/current-card recovery plus Ctrl+S, and offline British pronunciation controls.

Current embedded Oxford package remains 3308 entries. Existing pronunciation generation for those 3308 positions must not be regenerated wholesale without a specific defect.

## Spelling track checkpoint

Implemented as a second independent track using the same dictionary entry/custom-card IDs but separate persisted state in `spelling-state.json`:
- five permanent renameable spelling core decks;
- arbitrary stable-ID user spelling decks;
- independent per-dictionary spelling assignments and current card;
- create/rename/reorder/delete with safe transfer;
- native editable answer TextBox; Enter submits only from that control;
- Ukrainian prompt; exact English source string required;
- wrong answer cannot advance;
- Show Answer and pronunciation are hints and still require a correct typed answer;
- persisted completed reviews, first-try successes, wrong attempts, hint/show-answer counts, streak, recent outcomes and last-review timestamp;
- offline conservative scheduler behind `ISpellingScheduler`;
- scheduler automatically moves only among the five core spelling decks, never user-created decks;
- explainable coach moves, persisted coach on/off and reversible last coach move;
- all spelling commands and dynamic spelling deck switch/move actions use the existing persisted/conflict-checked/rebindable shortcut system;
- Spelling entry and spelling shortcut settings are exposed from the main Tools menu;
- dedicated regression tests cover independence from Recall, deck lifecycle, persistence, scheduler policy and shortcut rebinding/conflicts.

No claim of real NVDA verification is allowed until the user tests an actual Windows build with NVDA.

## Sentence Coach checkpoint

Durable design source remains `SENTENCE_COACH_PLAN.md`.

Implemented core:
- versioned `SentencePack`/`SentenceRecord` schema with EN/UA, stable IDs, source/license/provenance, normalized tokens, lemmas, target entry IDs, entry-level metadata, difficulty/off-list/quality metadata;
- in-memory inverted indexes by target entry ID and lemma;
- one-, two- and three-target intersection lookup contract;
- deterministic token normalization;
- Sentence Spelling token-multiset evaluator: exact required forms, word order explicitly not checked, missing/extra/duplicate diagnostics; edit distance is diagnostic only and never makes a misspelling correct;
- `SentenceSelector` enforcing user-selected target scope;
- deterministic personal/CEFR ranking with strong unknown-context/off-list penalties, mastered-context exemption, length/quality and recent-sentence penalties;
- controlled offline generator interface/fallback contract for missing corpus intersections;
- regression tests for versioning/provenance, tokenization, evaluator strictness, intersections, selected-scope leakage, personal-known ranking, recent avoidance and fallback contract.

Development-time Tatoeba EN-UA import pipeline is now implemented and regression-tested:
- accepts explicit 6-column EN/UA TSV (`EnglishId, lang, text, UkrainianId, lang, text`) and compact 4-column pair TSV;
- rejects malformed IDs, wrong language directions and invalid row shapes;
- preserves upstream English/Ukrainian sentence IDs in stable WordDeck sentence IDs;
- filters sentences that cannot currently be indexed against dictionary vocabulary and applies conservative length/quality flags;
- indexes every exact single-token Oxford surface match, including multiple stable entry IDs that share the same surface form;
- computes baseline off-list counts and CEFR difficulty from recognized context vocabulary;
- emits a validated versioned JSON `SentencePack` via the development CLI:
  `WordDeck.exe --build-tatoeba-sentence-pack <en-uk-pairs.tsv> <output.json> [pack-id]`;
- baseline lemmas are normalized surface forms. A later morphology preprocessing pass may replace them without changing stable sentence IDs or the pack schema;
- production Tatoeba EN-UA data is still not bundled in the repository or shipped application.

The code/self-test checkpoint that introduced this importer passed the full Windows workflow on 2026-08-17: build, Recall/Spelling/Sentence/Tatoeba self-tests, self-contained publish, published-EXE validation and artifact upload.

Tatoeba licensing provenance remains recorded in `THIRD_PARTY_NOTICES.md`. Before a real pack is committed/distributed, verify whether the selected export/subset is CC BY 2.0 FR or CC0 and preserve the exact required attribution; Tatoeba audio licensing is separate and is not covered by sentence-text reuse.

## Oxford content QA

Do not reset existing ledgers. Current first-pass translation checkpoint remains:
- reviewed through `oxford-a1-0240`;
- 240 reviewed;
- 208 verified;
- 32 needs-second-pass;
- 3068 remaining first-pass Oxford-3000 positions.

Oxford 5000 additions extraction/translation remains incomplete. Preserve POS/sense/CEFR distinctions and existing stable IDs. Do not claim Oxford 5000 complete until every included addition is accounted for and unresolved second-pass count is zero.

## Audio checkpoint

Latest Oxford-3000 British-audio batch workflow inspected on 2026-08-17 is green. Technical generation remains 3308/3308 positions; do not regenerate all files without a specific defect. Pronunciation QA and coherent offline AudioPack manifest/integrity assembly remain outstanding.

## Resume order

1. Fix any Windows CI/self-test regression before feature work.
2. Keep Spelling end-to-end behavior and migration stable without touching Recall state.
3. Produce a real development EN-UA SentencePack from a legally selected Tatoeba export/subset; inspect coverage/quality statistics before bundling anything.
4. Add runtime SentencePack loading plus one-target/two-target Sentence Spelling UI constrained to the selected Spelling scope.
5. Add morphology/lemma enrichment only where it materially improves coverage, then controlled deterministic generation for remaining corpus gaps.
6. Continue Oxford translation QA and AudioPack integrity/provenance work in remaining safe capacity.
7. Commit only to `worddeck-bootstrap` and keep published EXE self-test green before treating a slice as verified.
