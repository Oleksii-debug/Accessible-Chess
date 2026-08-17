# WordDeck third-party data notices

## Sentence Coach corpus pipeline

WordDeck's approved EN-UA SentencePack source is Tatoeba text data prepared only at development/build time. The shipped application remains self-contained/offline .NET and does not require Python, Tatoeba, a server, or an API at runtime.

Tatoeba's official downloads page states that downloadable text files are released under Creative Commons Attribution 2.0 France (CC BY 2.0 FR), with part of the sentence collection additionally available under CC0 1.0. The official Terms of Use state that textual sentences use CC BY 2.0 FR by default and that attribution is the reuse/distribution condition. The official Detailed Sentences export includes sentence ID, language, text and owner username.

Official references checked 2026-08-17:
- https://tatoeba.org/en/downloads
- https://tatoeba.org/en/terms_of_use
- https://downloads.tatoeba.org/exports/per_language/eng/
- https://downloads.tatoeba.org/exports/per_language/ukr/

### Strict CC0 pipeline and measured coverage

`tools/build_tatoeba_cc0_pairs.py` uses Python standard-library `bz2`, `urllib.request`, TSV/text and SHA-256 support only at development/build time. It loads the official English and Ukrainian CC0 sentence maps independently, intersects them with official EN-UA link IDs, and emits a pair only when BOTH text sides are independently present in their language-specific CC0 export. Its manifest hashes all three upstream inputs and the emitted pair TSV.

A production run against the official weekly exports on 2026-08-17 measured:
- 41,502 English CC0 sentences;
- 393 Ukrainian CC0 sentences;
- 217,546 unique EN-UA links inspected;
- 2 pairs with both sentence sides in the CC0 subsets.

The resulting verified CC0 SentencePack contained 2 accepted sentences and indexed 11 current Oxford entry IDs. This pipeline is provenance-safe but its present EN-UA coverage is too small to serve as WordDeck's practical Sentence Coach corpus by itself.

`TatoebaImportProvenance` verifies the adjacent manifest SHA-256 before allowing a pair TSV to propagate a CC0 label into a SentencePack. Missing, malformed or hash-mismatched manifests fail closed and are not trusted as CC0.

### Attributed CC BY supplement

Because strict both-side CC0 coverage is insufficient, WordDeck keeps that path intact and adds a separate attributed CC BY 2.0 FR supplement rather than weakening the CC0 rule.

`tools/build_tatoeba_ccby_pairs.py` reads the official per-language Detailed Sentences exports plus the official EN-UA links. It emits only pairs where both sentence sides have a usable Tatoeba owner username. The pair TSV preserves both upstream sentence IDs and both usernames. The SentencePack importer accepts this attributed layout and writes both author usernames and sentence IDs into each `SentenceRecord.Source`. Its adjacent manifest is SHA-256 verified before the importer trusts the attributed CC BY provenance.

The attributed path is development/build-time only and uses Python standard-library components; no new runtime library is introduced. A pack built from this path remains `CC BY 2.0 FR`, never CC0, and must ship with its attribution/license notice.

### Reuse decision: JSON/install/compression layer

Runtime SentencePack validation, serialization, installation and loading currently use only the .NET standard library: `System.Text.Json`, `System.IO`, and `System.IO.Compression.GZipStream`. The large attributed pack is stored as `.json.gz` and read directly through a decompression stream; WordDeck does not first materialize the whole JSON file as a .NET `string`. Existing uncompressed `.json` SentencePacks remain readable for backwards compatibility, while newly imported packs are canonicalized to gzip.

This was initially chosen after reuse-first review on 2026-08-17 because .NET 8 already provides maintained, Windows-compatible, offline, redistributable gzip streams and UTF-8 JSON stream deserialization. It solved the distribution-size problem without adding a runtime package: the 207,578-sentence attributed pack fell from 245,812,867 raw JSON bytes to 19,906,945 gzip bytes.

A subsequent real-runtime benchmark demonstrated that the eager object/index representation is too memory-heavy: load + validation/index construction took 5,303 ms on the Windows Actions runner and increased process working set by 628,666,368 bytes (managed-memory delta 543,390,448 bytes). The exact evidence is recorded in `QA/SENTENCEPACK_LOAD_QA_20260817.md` and the production artifact's `load-diagnostics.json`.

Because this is now a demonstrated requirement, disk-backed indexed storage is being evaluated before any custom streaming/container implementation. The leading reuse candidate is SQLite through `Microsoft.Data.Sqlite`: Microsoft's documentation describes it as a lightweight ADO.NET provider that can be used independently of Entity Framework; the provider is maintained in the .NET/EF Core repository under MIT. SQLite itself is serverless/single-file and its core is public domain. No SQLite package has been added to the shipped application yet; a measured read-only prototype must show materially lower working set without harming offline/self-contained Windows deployment before adoption.

Official references checked 2026-08-17:
- https://learn.microsoft.com/dotnet/api/system.io.compression.gzipstream
- https://learn.microsoft.com/dotnet/api/system.text.json.jsonserializer.deserialize
- https://learn.microsoft.com/dotnet/standard/data/sqlite/
- https://github.com/dotnet/efcore
- https://sqlite.org/about.html
- https://sqlite.org/copyright.html

### Reuse decision: BZip2 development exports

SharpCompress was evaluated on 2026-08-17 for direct development-time reading of Tatoeba `.bz2` exports. Its official project supports modern .NET and BZip2 and is MIT-licensed. It is not integrated because ingestion is development-only and Python's maintained standard-library `bz2`, `urllib.request`, TSV/text and hashing support already solve the task without increasing the shipped executable or NuGet dependency surface.

References checked 2026-08-17:
- https://github.com/adamhathcock/sharpcompress
- https://www.nuget.org/packages/SharpCompress/
- https://docs.python.org/3/library/bz2.html
- https://docs.python.org/3/library/urllib.request.html

Release rules for WordDeck SentencePacks:
1. Preserve stable upstream sentence/translation IDs whenever supplied.
2. Store source, provenance and license metadata in every SentencePack/record.
3. For CC BY 2.0 FR material, retain per-sentence attribution where available and ship the required license/attribution notice.
4. Never silently relabel CC BY material as CC0.
5. A CC0-labelled EN-UA pair requires BOTH sentence IDs to occur in their language-specific official CC0 exports; a translation link alone is not license proof.
6. Verify pair-manifest SHA-256 before propagating a license-specific provenance label into the pack.
7. Do not reuse Tatoeba audio merely because sentence text is reusable; audio has contributor-specific licensing and must be evaluated independently.
8. Do not bundle another corpus or preprocessing library until its redistribution license and provenance are reviewed here.

Synthetic regression sentences used only in source-code self-tests are marked as synthetic test data and are not presented as Tatoeba or human-verified corpus content.

## British pronunciation generation provenance

WordDeck's current British pronunciation generation is a development/build-time pipeline. The shipped Windows runtime does **not** require Kokoro, Python, espeak-ng, a network service or an API; it only plays already-generated MP3 files resolved by stable dictionary/entry ID.

Reuse-first review on 2026-08-17 retained the existing Kokoro generation path rather than introducing a new TTS subsystem. The official `hexgrad/Kokoro-82M` model card and repository declare Apache-2.0 licensing for the model/weights and document the British voices used by WordDeck: `bf_emma` and `bm_george` (`en-GB`/British English configuration).

Official references checked 2026-08-17:
- https://huggingface.co/hexgrad/Kokoro-82M
- https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md
- https://github.com/hexgrad/kokoro

The official Kokoro voice documentation also states that British English uses `lang_code='b'` in `misaki[en]` with an `en-gb` espeak-ng fallback. This existing G2P path is therefore the first place to resolve heteronym-specific pronunciation before considering any additional phoneme/NLP dependency.

### Reuse decision: pronunciation override validation

`Audio/pronunciation-overrides.tsv` and `tools/validate_pronunciation_overrides.py` are WordDeck-specific development-time glue, not a new TTS or NLP subsystem. The validator uses only Python standard-library `argparse`, `base64`, `csv`, `gzip`, `json` and `pathlib` to reconstruct and validate the already-embedded Oxford source, enforce stable-ID/source-text drift checks, and emit a targeted regeneration request. No new package, service, model, tokenizer or runtime dependency is introduced.

The ledger intentionally does not guess heteronym pronunciations. Formatting-only/sense-marker normalization may be marked `ready`; entries whose pronunciation changes by lexical sense remain `review` until the existing British G2P/phonetic path or listening QA establishes the intended form. This keeps the reuse-first Kokoro/Misaki/espeak-ng generation route and avoids unreliable spelling hacks.

The generation environment may use support components such as espeak-ng for phonemization/fallback. Those generation-tool dependencies are not shipped as WordDeck runtime dependencies and must not be described as such. Final AudioPack distribution must retain appropriate Kokoro/model generation attribution and license notices, plus any notices required by components actually redistributed with the pack or application.

The 2026-08-17 aggregate integrity audit of all seven existing Oxford 3000 generation artifacts is recorded in `Audio/OXFORD3000_AUDIO_INTEGRITY_QA_20260817.md`. It verified 3,308 unique stable-ID audio records with matching packaged byte sizes, while separately identifying pronunciation-normalization work still required for sense markers, parenthetical labels, homographs and acronyms.
