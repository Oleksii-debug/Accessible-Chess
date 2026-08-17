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

The Sentence Spelling file picker now exposes `.json.gz` as a first-class supported format alongside legacy `.json`, and its accessible pack control/no-pack guidance explicitly identifies both supported offline formats. This is UI glue only; no new parser, storage layer or runtime dependency was introduced. Windows gate for commit `8a284ddd1b4c0b30700cfbe0af95b7bfb3cd28d8` passed build, embedded-dictionary validation, self-contained publish, published-EXE validation and artifact upload.

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

Technical generation remains **3,308 / 3,308** and no wholesale regeneration is justified.

The aggregate structural audit remains green: 3,308 unique stable IDs/indexes, exact range 0–3307, zero manifest/package byte-size mismatches, all `en-GB`, speed `1.0`, 24 kHz target, `bf_emma` 1,675 and `bm_george` 1,633.

### Pronunciation override ledger — implemented, targeted regeneration pending

`Audio/pronunciation-overrides.tsv` now records all 36 numbered/sense-marker candidates identified by the aggregate audit and is keyed by stable Oxford entry ID plus exact source text. The ledger deliberately separates:
- **19 `ready` overrides** where removing the superscript/parenthetical marker does not change the intended lexical pronunciation;
- **17 `review` heteronym/sense-sensitive entries** such as `close`, `live`, `lead`, `refuse`, `wind`, `content`, `row`, `used` and `tear`, where guessing a plain-text pronunciation would be unsafe.

`tools/validate_pronunciation_overrides.py` is a development-time standard-library-only validator. It reconstructs the actual embedded Oxford TSV from the existing base64+gzip source parts, requires exactly 3,308 entries, verifies every ledger stable ID and exact source string, rejects duplicate/drifted/unsafe rows, detects the five uppercase candidates (`CD`, `DVD`, `IT`, `OK`, `TV`), and emits a deterministic targeted-regeneration JSON request containing only the 19 ready overrides while keeping the 17 heteronyms and uppercase candidates explicitly blocked for phonetic/listening QA.

The Windows workflow now runs this validator before .NET restore/build and uploads the regeneration request as a separate development artifact. No Python/Kokoro dependency was added to the shipped WordDeck runtime.

Reuse-first review retained the existing Kokoro British path. Official Kokoro documentation confirms British voices use `lang_code='b'` with `misaki[en]` and `en-gb` espeak-ng fallback; current WordDeck voices remain `bf_emma` and `bm_george`. Exact phonetic forcing for the 17 heteronyms must use the existing generation/G2P path or a validated supported phoneme mechanism, not spelling hacks.

Evidence remains in `Audio/OXFORD3000_AUDIO_INTEGRITY_QA_20260817.md`; reuse/provenance is recorded in `THIRD_PARTY_NOTICES.md`.

## Exact next steps

1. Keep Windows CI and published-EXE validation green.
2. Measure load time and working-set behavior on the real 19.9 MB / 207,578-sentence `.json.gz` pack using built-in .NET diagnostics before considering optimization; optimize only if measurement shows a problem.
3. Use the generated pronunciation request to regenerate only the 19 safe normalization entries; resolve the 17 heteronyms and 5 uppercase candidates with deterministic British G2P/phonetic or listening QA before adding them to the ready set; then assemble the coherent AudioPack with stable-ID hashes/manifest.
4. Resolve the 188 recorded SentencePack coverage-gap IDs to exact Oxford source/POS records and classify root causes before adding morphology or controlled generation.
5. Continue Oxford-5000 extraction/translation/second-pass QA in substantial batches.
6. Never modify `main`.
