# WordDeck development checkpoint

Last updated: 2026-08-17
Branch: `worddeck-bootstrap` only. Never develop WordDeck on `main`.

## Verified product baseline

Recall remains green: five permanent renameable core decks plus user decks, stable IDs/shortcuts, no-repeat shuffle bag, custom cards, autosave/backup/current-card recovery, Ctrl+S and optional offline British pronunciation.

Spelling remains an independent persisted track with five core plus user decks, exact native-TextBox spelling, wrong-answer lock, required correct typing after hints, objective stats, conservative offline coach moves only among core spelling decks, undo/explanations and rebindable persisted commands.

Sentence Spelling remains green with installed pack selection, spelling-deck scope, 1- or 2-target exercises, Ukrainian prompt, native English TextBox, Enter submit, token/form multiset evaluation with word order intentionally ignored, concise error diagnosis, required correct typing after Show Answer, persisted stats/recent/current exercise and same-scope two-target intersections.

Do not claim NVDA verification until the user tests an actual Windows build with NVDA.

## SentencePack corpus and storage

Strict both-side Tatoeba CC0 remains too small for primary use: 2 EN-UA pairs and 11 current Oxford entry IDs.

Attributed `CC BY 2.0 FR` production pack remains:
- 207,578 accepted EN-UA sentences;
- 3,120 / 3,308 current Oxford entry IDs covered;
- 190,315 sentences with at least 2 indexed targets;
- 160,058 with at least 3;
- 53,612 quality-flagged;
- 0 accepted records missing per-side author attribution.

JSON/GZIP remains the backwards-compatible interchange/import format. The real pack is 245,812,867 raw JSON bytes and 19,906,945 gzip bytes (91.9% reduction).

### Compact SQLite runtime path — measured and partially integrated

Reuse-first evaluation selected Microsoft's maintained MIT-licensed `Microsoft.Data.Sqlite` provider rather than a custom binary/index engine. Version 8.0.29 is pinned on the .NET 8 servicing line. SQLite core is public domain and remains local/serverless/offline.

The eager JSON/GZIP runtime representation is confirmed too large: production measurements are about 5.2–5.3 seconds load time, +543 MB managed memory and +625–629 MB process working set.

The first SQLite proof reduced fresh-query working set to ~27 MB but produced a 341,766,144-byte database because it duplicated full JSON payloads and text-key indexes.

Commit `858efb143ba5a9c4a0c5dccfb41de10de07af5c5` introduced compact schema v2: integer sentence/target keys, dictionary-encoded Oxford IDs, compact CEFR values, column-wise runtime fields, canonical token reconstruction, optional lemma overrides, and selective SQLite `WITHOUT ROWID` composite-key tables.

Production attributed workflow run `32054968152` verified on the full 207,578-sentence pack:
- database: **72,400,896 bytes** (78.8% smaller than prototype v1);
- fresh-process one-target query: **158 ms**;
- result count: 1,141;
- managed-memory delta: **2,172,960 bytes**;
- working-set delta: **24,375,296 bytes**;
- same-run eager working-set delta: 624,680,960 bytes.

This is about a **96.1% incremental working-set reduction** for the representative query. Full details are in `QA/SENTENCEPACK_LOAD_QA_20260817.md`.

The first integration slice is now implemented and regression-tested:
- `ISentenceCorpus` is the narrow shared query contract used by `SentenceSelector`;
- `SentencePackSqliteCorpus` exposes schema-v2 SQLite through the same 1/2/3-target query contract;
- importing a `.json`/`.json.gz` SentencePack validates the portable pack, preserves canonical gzip interchange, builds a stable `.sqlite` companion, and exposes the companion as the intended runtime corpus;
- same-pack replacement rebuilds the companion at the same stable path;
- Windows-specific file replacement clears `Microsoft.Data.Sqlite` connection pools before the atomic move, fixing a real CI file-lock regression;
- store self-tests cover SQLite companion creation, lookup, reload discovery and replacement.

The remaining memory-critical step is **not finished yet**: `LoadInstalled()` still eagerly reads the gzip pack to populate the existing UI model, and Sentence Coach UI still holds the in-memory `SentencePack`. Next work must switch installed-pack discovery/UI to `ISentenceCorpus` metadata/query access so restart/study no longer materializes 207,578 records. Do not claim the large-corpus runtime RAM problem fully solved until that path is measured end-to-end.

### Current Oxford coverage gaps

The production attributed pack leaves exactly 188 current Oxford IDs uncovered:
- A1: 23;
- A2: 35;
- B1: 54;
- B2: 76.

The reproducible list remains `QA/sentence_coverage_gaps_20260817.txt`. No morphology or generator fallback has been added. Resolve exact source/POS records and classify tokenization, inflection-only coverage, rare/symbolic entries, corpus absence and indexing defects before selecting a fallback.

## Oxford 5000

Embedded package remains 3,308 current Oxford-3000 positions.

Oxford-3000 translation QA checkpoint remains: 240 reviewed, 208 verified, 32 needs-second-pass, 3,068 remaining first-pass positions.

Oxford-5000 additions extraction is incomplete. The currently extracted first 100 B2/C1 additions have Ukrainian translations; clear senses are `verified`, ambiguous/polysemous/multi-POS items remain `needs_second_pass`. Do not claim Oxford 5000 complete until the full additions set is extracted and unresolved second-pass count reaches zero.

## British audio

Technical generation remains 3,308 / 3,308. No wholesale regeneration is justified.

Aggregate structural audit remains green: 3,308 unique stable IDs/indexes, exact 0–3307 range, zero byte-size mismatches, all `en-GB`, speed 1.0, 24 kHz target; `bf_emma` 1,675 and `bm_george` 1,633.

`Audio/pronunciation-overrides.tsv` contains 36 numbered/sense-marker candidates: 19 formatting-only entries are `ready` for targeted regeneration; 17 heteronym/sense-sensitive entries remain `review`. Five uppercase candidates (`CD`, `DVD`, `IT`, `OK`, `TV`) also remain explicit QA items. The development validator reconstructs the embedded Oxford source, fails closed on ID/source drift, and emits only the 19 safe regeneration requests. Runtime still does not depend on Kokoro/Python/API/network.

## CI checkpoint

Attributed SentencePack workflow run `32054968152` for compact schema v2 completed fully `success`, including corpus rebuild, attribution/coverage validation, gzip packaging, compact SQLite conversion and isolated fresh-process query benchmark.

During import integration, Windows CI correctly exposed a pooled SQLite Windows file-handle lock on the temporary database. Commit `d1d77efe19b2f039aae064ad93b96bf5c25b3303` fixed the lifecycle by clearing provider pools before atomic replacement. Windows workflow run `32055830328` then completed fully `success`: provenance/audio validations, restore, build, all extended self-tests including SQLite companion import/replacement, embedded dictionary validation, self-contained publish, published-EXE validation and artifact uploads.

## Exact next steps

1. Preserve green Windows CI/published-EXE validation.
2. Finish the disk-backed vertical slice: make installed-pack discovery and Sentence Coach UI use `ISentenceCorpus` metadata/query access directly so app restart/study does not eagerly load the large gzip pack.
3. Measure real post-integration startup/one-target/two-target working set and latency on the 207,578-sentence corpus; keep legacy `.json/.json.gz` fallback and corruption isolation.
4. Resolve/classify the 188 coverage-gap IDs before adding morphology or controlled generation.
5. Regenerate only the 19 safe pronunciation overrides; resolve 17 heteronyms plus 5 uppercase candidates before completing AudioPack QA.
6. Continue Oxford-5000 extraction/translation/second-pass QA in substantial batches after the next user-testable runtime milestone.
7. Never modify `main`.
