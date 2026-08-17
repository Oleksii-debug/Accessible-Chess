# WordDeck development checkpoint

Last updated: 2026-08-17
Branch: `worddeck-bootstrap` only. Never develop WordDeck on `main`.

## Verified product baseline

Recall remains green: five permanent renameable core decks plus user decks, stable IDs/shortcuts, no-repeat shuffle bag, custom cards, autosave/backup/current-card recovery, Ctrl+S and optional offline British pronunciation.

Spelling remains an independent persisted track with five core plus user decks, exact native-TextBox spelling, wrong-answer lock, required correct typing after hints, objective stats, conservative offline coach moves only among core spelling decks, undo/explanations and rebindable persisted commands.

Sentence Spelling remains green with installed pack selection, spelling-deck scope, 1- or 2-target exercises, Ukrainian prompt, native English TextBox, Enter submit, token/form multiset evaluation with word order intentionally ignored, concise error diagnosis, required correct typing after Show Answer, persisted stats/recent/current exercise and same-scope two-target intersections.

Do not claim NVDA verification until the user tests an actual Windows build with NVDA.

## SentencePack corpus and runtime storage

Strict both-side Tatoeba CC0 remains too small for primary use: 2 EN-UA pairs and 11 current Oxford entry IDs.

Attributed `CC BY 2.0 FR` production pack remains:
- 207,578 accepted EN-UA sentences;
- 3,120 / 3,308 current Oxford entry IDs covered;
- 190,315 sentences with at least 2 indexed targets;
- 160,058 with at least 3;
- 53,612 quality-flagged;
- 0 accepted records missing per-side author attribution.

JSON/GZIP remains the portable interchange/import format. The current production pack is about 245.8 MB raw JSON and 19.9 MB gzip.

### Disk-backed SQLite runtime — large-corpus blocker closed

Reuse-first evaluation selected Microsoft's maintained MIT-licensed `Microsoft.Data.Sqlite` provider rather than a custom binary/index engine. Version 8.0.29 remains pinned on the .NET 8 servicing line. SQLite core is public domain and remains local/serverless/offline. No new runtime service, Python, Java, API, sentence cache or custom storage engine was introduced for this optimization.

The old eager JSON/GZIP representation measured about 5 seconds load time and roughly +0.6 GB process working set. The compact schema-v2 SQLite database is 72,400,896 bytes and remains the preferred installed runtime representation.

An end-to-end production benchmark first reproduced the actual Sentence Coach bottleneck before changing it. On the full 3,308-entry Oxford scope, repeated per-entry SQL sentence materialization took:
- one-target coverage: 32,635 ms for 3,120 covered entries;
- same-scope two-target coverage: 32,093 ms for 3,114 covered entries.

The UI now uses one WordDeck-specific batched SQLite scope query instead. It loads scope target IDs into a connection-local temporary table in bounded chunks and uses existing `sentence_targets` indexes plus `EXISTS` queries. It returns only covered entry IDs; it does not materialize corpus sentences for coverage calculation. Legacy JSON/GZIP fallback retains the prior behavior.

Verified production benchmark after the change on the same 207,578-sentence corpus:
- SQLite corpus metadata open: 79 ms;
- one-target coverage: **33 ms**, 3,120 / 3,308 entries;
- same-scope two-target coverage: **56 ms**, 3,114 / 3,308 entries;
- representative one-target sentence query: 179 ms, 3,075 candidates;
- representative two-target intersection: 13 ms, 238 candidates;
- measured runtime diagnostic delta: about 31.5 MB managed memory and 49.9 MB working set while retaining the benchmark result sets.

This reduces the measured full-scope coverage phase from about **64.7 seconds to 89 ms**, while preserving the exact 3,120 one-target and 3,114 two-target coverage counts. The large-corpus startup/coverage RAM-and-latency blocker is therefore closed for the current SQLite path.

Windows workflow run `32065274229` on commit `c6e166046167c6596be23515e47c11d8c8dac15d` completed fully `success`: provenance/audio validations, restore, build, self-tests, embedded dictionary validation, self-contained publish, published-EXE validation and artifacts.

Attributed SentencePack workflow run `32065274247` on the same commit also completed fully `success`, including current Tatoeba rebuild/provenance validation, gzip, SQLite construction, fresh-query measurement, the new full-scope Sentence Coach benchmark and artifact upload.

`SentencePackStore.LoadInstalled()` still discovers valid SQLite companions from metadata without eagerly materializing matching portable packs. Corrupt/missing SQLite is isolated and the portable JSON/GZIP path remains a compatibility fallback. Current-exercise restoration re-queries saved stable IDs instead of retaining the whole corpus.

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

`Audio/pronunciation-overrides.tsv` contains 36 numbered/sense-marker candidates: 19 formatting-only entries are `ready` for targeted regeneration; 17 heteronym/sense-sensitive entries remain `review`. Five uppercase candidates (`CD`, `DVD`, `IT`, `OK`, `TV`) also remain explicit QA items. Runtime still does not depend on Kokoro/Python/API/network.

## Exact next steps

1. Keep Windows CI/published-EXE validation green; preserve the new batched SQLite coverage path with a focused regression check.
2. Resolve/classify the 188 SentencePack coverage-gap IDs before adding morphology or controlled generation.
3. Regenerate only the 19 safe pronunciation overrides; resolve 17 heteronyms plus 5 uppercase candidates before completing AudioPack QA.
4. Continue Oxford-5000 extraction/translation/second-pass QA in substantial batches now that the Sentence Coach large-corpus runtime blocker is closed.
5. Continue Oxford-3000 semantic translation QA without blocking already-usable Recall/Spelling/Sentence vertical slices.
6. Never modify `main`.
