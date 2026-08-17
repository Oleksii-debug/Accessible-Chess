# WordDeck development checkpoint

Last updated: 2026-08-18
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

An end-to-end production benchmark first reproduced the actual Sentence Coach bottleneck before changing it. On the full 3,308-entry Oxford scope, repeated per-entry SQL sentence materialization took 32,635 ms for one-target coverage and 32,093 ms for same-scope two-target coverage.

The UI now uses one WordDeck-specific batched SQLite scope query instead. It loads scope target IDs into a connection-local temporary table in bounded chunks and uses existing `sentence_targets` indexes plus `EXISTS` queries. It returns only covered entry IDs; it does not materialize corpus sentences for coverage calculation. Legacy JSON/GZIP fallback retains the prior behavior.

Verified production benchmark after the change on the same 207,578-sentence corpus:
- SQLite corpus metadata open: 79 ms;
- one-target coverage: **33 ms**, 3,120 / 3,308 entries;
- same-scope two-target coverage: **56 ms**, 3,114 / 3,308 entries;
- representative one-target sentence query: 179 ms, 3,075 candidates;
- representative two-target intersection: 13 ms, 238 candidates;
- measured runtime diagnostic delta: about 31.5 MB managed memory and 49.9 MB working set while retaining the benchmark result sets.

This reduces the measured full-scope coverage phase from about **64.7 seconds to 89 ms**, while preserving the exact 3,120 one-target and 3,114 two-target coverage counts.

Windows workflow run `32065274229` and attributed SentencePack run `32065274247` on commit `c6e166046167c6596be23515e47c11d8c8dac15d` completed fully `success`.

`SentencePackStore.LoadInstalled()` discovers valid SQLite companions from metadata without eagerly materializing matching portable packs. Corrupt/missing SQLite is isolated and the portable JSON/GZIP path remains a compatibility fallback. Current-exercise restoration re-queries saved stable IDs instead of retaining the whole corpus.

### Current Oxford coverage gaps — structural resolution completed

The production attributed pack still reports exactly 188 current Oxford IDs without a `TargetEntryId`: A1 23, A2 35, B1 54, B2 76. The reproducible source list remains `QA/sentence_coverage_gaps_20260817.txt`.

A new standard-library-only development QA tool, `tools/resolve_sentence_coverage_gaps.py`, reconstructs the same embedded Oxford TSV from its base64+gzip parts, resolves every gap ID to the exact source/translation record and emits an Actions TSV artifact. It does not ship with the WordDeck runtime.

Verified resolver result on all 188 gaps:
- **114** are ordinary single-surface entries that the current exact surface index is capable of indexing. These now represent the genuine next corpus/morphology investigation set: corpus absence, inflection-only occurrence or another evidence-based matching gap.
- **74** are structurally outside the current single-surface index before corpus frequency is even considered: 42 multiword/annotated forms, 29 numbered/sense-marker forms and 3 noncanonical hyphenated forms.

This proves that the previous raw count of 188 mixed two different problems. Do not add blanket marker stripping: examples such as `can¹`/`can²`, `close¹`/`close²`, `wind¹`/`wind²` and parenthetical sense labels would otherwise map one corpus token to semantically distinct Oxford records. Multiword phrases should be separated from sense-annotated entries before any matching extension.

Windows workflow run `32069531842` on commit `20ee069c02f7f7897af8070568872ccb6ba54f10` completed fully `success`: new gap-resolver validation and artifact generation, pronunciation-ledger validation, restore, build, all self-tests, embedded dictionary validation, self-contained publish, published-EXE validation and artifact uploads.

## Oxford 5000

Embedded package remains 3,308 current Oxford-3000 positions.

Oxford-3000 translation QA checkpoint remains: 240 reviewed, 208 verified, 32 needs-second-pass, 3,068 remaining first-pass positions.

Oxford-5000 additions extraction is incomplete. The currently extracted first 100 B2/C1 additions have Ukrainian translations; clear senses are `verified`, ambiguous/polysemous/multi-POS items remain `needs_second_pass`. Do not claim Oxford 5000 complete until the full additions set is extracted and unresolved second-pass count reaches zero.

Official Oxford Learner's Dictionaries remains the authoritative extraction reference: Oxford describes the Oxford 5000 as the Oxford 3000 plus 2,000 additional B2-C1 words, with word/POS/CEFR data exposed in the official list.

## British audio

Technical generation remains 3,308 / 3,308. No wholesale regeneration is justified.

Aggregate structural audit remains green: 3,308 unique stable IDs/indexes, exact 0–3307 range, zero byte-size mismatches, all `en-GB`, speed 1.0, 24 kHz target; `bf_emma` 1,675 and `bm_george` 1,633.

`Audio/pronunciation-overrides.tsv` contains 36 numbered/sense-marker candidates: 19 formatting-only entries are `ready` for targeted regeneration; 17 heteronym/sense-sensitive entries remain `review`. Five uppercase candidates (`CD`, `DVD`, `IT`, `OK`, `TV`) also remain explicit QA items. Runtime still does not depend on Kokoro/Python/API/network.

## Reuse/provenance decisions in this cycle

No new runtime subsystem was introduced. The new gap resolver is development-only deterministic glue using Python standard-library `base64`, `gzip` and `csv`; it reuses the repository's existing embedded dictionary package and exact gap ledger. No external NLP/tokenizer/morphology component was added, because this cycle only establishes evidence for the next matching decision.

## Exact next steps

1. Keep Windows CI/published-EXE validation green.
2. Split the 74 structurally unindexable gaps into safe exact multiword/hyphen candidates versus sense-annotated records; do not collapse sense distinctions.
3. For the 114 ordinary single-surface gaps, use the production attributed Tatoeba pair input to measure exact occurrence, inflected-form-only occurrence and genuine corpus absence before choosing morphology/fallback.
4. Only after that evidence, evaluate reusable maintained morphology/lemmatization options before writing any such component; prefer no runtime dependency if exact phrase matching closes a meaningful safe subset.
5. Regenerate only the 19 safe pronunciation overrides; resolve 17 heteronyms plus 5 uppercase candidates before completing AudioPack QA.
6. Continue Oxford-5000 extraction/translation/second-pass QA in substantial batches; continue Oxford-3000 semantic translation QA without blocking usable Recall/Spelling/Sentence slices.
7. Never modify `main`.
