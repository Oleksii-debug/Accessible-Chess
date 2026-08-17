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

JSON/GZIP remains the portable interchange/import format. The production pack is 245,812,867 raw JSON bytes and 19,906,945 gzip bytes.

### Disk-backed SQLite path

Reuse-first evaluation selected Microsoft's maintained MIT-licensed `Microsoft.Data.Sqlite` provider rather than a custom binary/index engine. Version 8.0.29 remains pinned on the .NET 8 servicing line. SQLite core is public domain and remains local/serverless/offline.

The old eager JSON/GZIP runtime representation measured about 5.2–5.3 seconds load time, +543 MB managed memory and +625–629 MB process working set.

Compact schema v2 production measurement remains:
- SQLite database: 72,400,896 bytes;
- fresh-process one-target query: 158 ms;
- managed-memory delta: 2,172,960 bytes;
- working-set delta: 24,375,296 bytes;
- about 96.1% less incremental working set than the eager representation for that representative query.

### Runtime vertical slice now implemented

The memory-critical restart/study path has now been changed:
- `SentencePackStore.LoadInstalled()` discovers valid `.sqlite` companions first and reads pack id/license/count directly from SQLite metadata instead of eagerly deserializing the matching `.json.gz`;
- installed portable gzip/JSON remains present for provenance/export/backwards compatibility;
- corrupt/missing SQLite is isolated and the portable pack remains the compatibility fallback;
- `SentenceCoachForm` now holds `ISentenceCorpus`, not `SentencePack`, so one-target selection, two-target intersections, candidate ranking and exercise restoration query the disk-backed corpus directly;
- persisted current sentence restoration no longer scans `SentencePack.Sentences`; it re-queries the saved target intersection and matches the saved stable sentence ID;
- import still performs one deliberate full validation/build pass, then returns the SQLite runtime corpus;
- store self-tests explicitly assert that normal post-restart discovery does not retain/materialize the portable `SentencePack` when a valid SQLite companion exists;
- legacy standalone `.json`/`.json.gz` packs without SQLite still load through the existing in-memory path.

Windows workflow run `32058598541` on commit `4fef2f56e17b3490f960fda212c45dc98ece5f48` completed fully `success`: provenance/audio validations, restore, build, extended self-tests including metadata-only SQLite discovery, embedded dictionary validation, self-contained publish, published-EXE validation and artifact uploads.

The large-corpus RAM issue is **not yet declared fully closed**. The remaining required proof is an end-to-end startup/one-target/two-target measurement through the actual Sentence Coach runtime path. Coverage calculation currently performs repeated corpus lookups and must be included in that latency measurement before release claims.

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

1. Keep Windows CI/published-EXE validation green.
2. Add an isolated end-to-end benchmark for normal installed-pack discovery plus Sentence Coach one-target and two-target queries on the 207,578-sentence SQLite corpus; include coverage-calculation latency and working set.
3. If coverage calculation is measurably slow, replace repeated per-target SQL calls with a small SQLite batch query/indexed-target metadata path rather than caching sentence objects in RAM.
4. Resolve/classify the 188 coverage-gap IDs before adding morphology or controlled generation.
5. Regenerate only the 19 safe pronunciation overrides; resolve 17 heteronyms plus 5 uppercase candidates before completing AudioPack QA.
6. Continue Oxford-5000 extraction/translation/second-pass QA in substantial batches after the next user-testable runtime milestone.
7. Never modify `main`.
