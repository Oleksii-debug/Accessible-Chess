# WordDeck development checkpoint

Last updated: 2026-08-17
Branch: `worddeck-bootstrap` only. Never develop WordDeck on `main`.

## Verified baseline

Recall remains green: five permanent renameable core decks plus user decks, stable IDs/shortcuts, no-repeat shuffle bag, custom cards, autosave/backup/current-card recovery, Ctrl+S and optional offline British pronunciation.

Spelling remains an independent persisted track with five core plus user decks, exact native-TextBox spelling, wrong-answer lock, required correct typing after hints, objective stats, conservative offline coach moves only among core spelling decks, undo/explanations and rebindable persisted commands.

Sentence Spelling remains green with installed pack selection, spelling-deck scope, 1- or 2-target exercises, Ukrainian prompt, native English TextBox, Enter submit, token/form multiset evaluation with word order intentionally ignored, concise error diagnosis, required correct typing after Show Answer, persisted stats/recent/current exercise and same-scope two-target intersections.

Do not claim NVDA verification until the user tests a Windows build with NVDA.

## Tatoeba SentencePack

Strict both-side CC0 remains too small for primary use: 2 EN-UA pairs and 11 current Oxford entry IDs.

Attributed `CC BY 2.0 FR` production pack remains:
- 207,578 accepted EN-UA sentences;
- 3,120 / 3,308 current Oxford entry IDs covered;
- 190,315 sentences with at least 2 indexed targets;
- 160,058 with at least 3;
- 53,612 quality-flagged;
- 0 accepted records missing per-side author attribution.

### Practical gzip packaging — verified

Reuse-first review selected built-in .NET 8 `System.IO.Compression.GZipStream` and `System.Text.Json` stream deserialization. No new runtime dependency was added.

`SentencePackStore` accepts plain `.json` and `.json.gz`, reads gzip through a decompression stream, stores new imports canonically as `.json.gz`, keeps legacy `.json` compatibility and isolates malformed optional packs.

Real attributed pipeline measurement on 2026-08-17:
- raw JSON: 245,812,867 bytes;
- gzip: 19,906,945 bytes;
- reduction: 91.9%;
- corpus and attribution counts unchanged.

The attributed Actions artifact contains the gzip pack plus provenance/coverage/compression reports instead of the 246 MB raw JSON. Reuse/provenance decisions are recorded in `THIRD_PARTY_NOTICES.md`.

### Exact current-Oxford coverage gaps — verified

The successful real attributed SentencePack artifact was inspected directly and its `TargetEntryIds` were compared with the current deterministic Oxford ID ranges enforced by self-tests. Exact uncovered count is 188:
- A1: 23;
- A2: 35;
- B1: 54;
- B2: 76.

The complete reproducible ID list is recorded in `QA/sentence_coverage_gaps_20260817.txt`. No morphology or generator fallback has been added from this result. Next gap work must resolve IDs to exact source/POS records and classify tokenization, inflection-only coverage, corpus absence and indexing defects before choosing any fallback.

## Oxford 5000

Embedded package remains 3,308 current Oxford-3000 positions.

Oxford-3000 translation QA checkpoint remains: 240 reviewed, 208 verified, 32 needs-second-pass, 3,068 remaining first-pass positions.

Oxford-5000 additions extraction is incomplete. The currently extracted first 100 B2/C1 additions have Ukrainian translations; clear senses are `verified`, ambiguous/polysemous/multi-POS items remain `needs_second_pass`. Do not claim Oxford 5000 complete until the full additions set is extracted and unresolved second-pass count reaches zero.

## British audio

Technical generation remains 3,308 / 3,308. Do not regenerate wholesale. Pronunciation QA and coherent AudioPack manifest/integrity packaging remain outstanding; generate additions audio only after Oxford-5000 entries are stable.

## Exact next steps

1. Keep Windows CI and published-EXE validation green.
2. Add first-class `.json.gz` selection/help in SentencePack UI and measure load-time/working-set behavior on the real 19.9 MB / 207,578-sentence pack; optimize only if measurement shows a problem.
3. Resolve the 188 recorded coverage-gap IDs to exact Oxford source/POS records and classify root causes before adding morphology or controlled generation.
4. Continue Oxford-5000 extraction/translation/second-pass QA in substantial batches.
5. Continue British AudioPack QA/integrity packaging.
6. Never modify `main`.
