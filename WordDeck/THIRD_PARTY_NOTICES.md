# WordDeck third-party data and component notices

## Sentence Coach corpus pipeline

WordDeck's approved EN-UA SentencePack source is Tatoeba text data prepared at development/build time. The shipped application remains self-contained/offline .NET and does not require Python, Tatoeba, a server, API or LLM at runtime.

Tatoeba's official downloads page states that downloadable text files are released under Creative Commons Attribution 2.0 France (CC BY 2.0 FR), with part of the sentence collection additionally available under CC0 1.0. The official Detailed Sentences export includes sentence ID, language, text and owner username.

Official references checked 2026-08-17:
- https://tatoeba.org/en/downloads
- https://tatoeba.org/en/terms_of_use
- https://downloads.tatoeba.org/exports/per_language/eng/
- https://downloads.tatoeba.org/exports/per_language/ukr/

### Strict CC0 pipeline

`tools/build_tatoeba_cc0_pairs.py` uses Python standard-library components only at development/build time. It independently loads official English and Ukrainian CC0 sentence maps, intersects them with official EN-UA links, and emits a pair only when BOTH text sides are present in the corresponding language-specific CC0 export. Its manifest hashes all upstream inputs and output with SHA-256.

A production run on 2026-08-17 measured 41,502 English CC0 sentences, 393 Ukrainian CC0 sentences and 217,546 unique EN-UA links, yielding only 2 both-side-CC0 pairs. The resulting verified SentencePack covered 11 current Oxford entry IDs. This path is provenance-safe but too small for primary Sentence Coach use.

`TatoebaImportProvenance` verifies the adjacent manifest before allowing a license-specific provenance label to propagate. Missing, malformed or hash-mismatched manifests fail closed.

### Attributed CC BY supplement

Because strict both-side CC0 coverage is insufficient, WordDeck keeps that path intact and uses a separate attributed CC BY 2.0 FR supplement rather than weakening the CC0 rule.

`tools/build_tatoeba_ccby_pairs.py` reads official Detailed Sentences exports plus EN-UA links. It emits only pairs where both sides have usable Tatoeba owner usernames. Pair TSV and SentencePack records preserve upstream sentence IDs and both author usernames. The adjacent manifest is SHA-256 verified before attributed provenance is trusted.

The production attributed pack contains 207,578 EN-UA pairs and remains `CC BY 2.0 FR`; it must ship with the required attribution/license notice.

### Reuse decision: JSON/GZIP interchange

SentencePack import/interchange uses .NET standard-library `System.Text.Json`, `System.IO` and `System.IO.Compression.GZipStream`. Existing `.json` remains readable and `.json.gz` is the preferred compact interchange form.

The production pack fell from 245,812,867 raw JSON bytes to 19,906,945 gzip bytes (91.9% reduction). A real runtime benchmark nevertheless showed that eagerly materializing all records plus duplicate indexes costs about +543 MB managed memory and +625–629 MB process working set. Therefore gzip remains the interchange format but not the preferred large-pack runtime representation.

Official references checked 2026-08-17:
- https://learn.microsoft.com/dotnet/api/system.io.compression.gzipstream
- https://learn.microsoft.com/dotnet/api/system.text.json.jsonserializer.deserialize

### Reuse decision: SQLite disk-backed runtime candidate

Before implementing a custom binary/index subsystem, WordDeck evaluated SQLite through Microsoft's maintained `Microsoft.Data.Sqlite` ADO.NET provider. The provider is part of the .NET/EF Core project, is MIT-licensed, works without Entity Framework, is compatible with self-contained Windows .NET deployment and requires no server or network. SQLite core is public domain and serverless/single-file.

`Microsoft.Data.Sqlite` **8.0.29** is now pinned in `WordDeck.csproj` for the measured .NET 8 prototype. This is a deliberate reuse choice rather than a home-grown storage engine. The current JSON/GZIP format remains backwards-compatible import/interchange while the disk-backed runtime path is integrated and tested.

The first proof schema confirmed the memory benefit but was too large: 341,766,144 bytes because it stored full serialized `SentenceRecord` JSON plus string-key indexes. A fresh-process representative query used +3,117,584 managed bytes and +27,217,920 working-set bytes.

Compact schema v2 (commit `858efb143ba5a9c4a0c5dccfb41de10de07af5c5`) reuses standard SQLite relational features instead of introducing a custom container: integer row IDs, dictionary-encoded Oxford target IDs, compact CEFR integers and column-wise runtime fields. Canonical tokens are deterministically rebuilt from English text; lemma data is stored only as an override when it differs from canonical tokens. `WITHOUT ROWID` is used selectively for compact composite-key/link tables, following SQLite's documented storage model rather than applying it indiscriminately.

Production workflow run `32054968152` measured the full 207,578-sentence corpus at:
- SQLite database: 72,400,896 bytes;
- fresh-process representative query: 158 ms;
- 1,141 returned candidate sentences;
- managed-memory delta: 2,172,960 bytes;
- working-set delta: 24,375,296 bytes.

This is a material runtime-memory win versus the same run's 624,680,960-byte eager working-set delta. The measured result justifies proceeding with the smallest disk-backed query integration; it does not justify removing JSON/GZIP compatibility.

Official references checked 2026-08-17:
- https://learn.microsoft.com/dotnet/standard/data/sqlite/
- https://www.nuget.org/packages/Microsoft.Data.Sqlite/8.0.29
- https://github.com/dotnet/efcore
- https://sqlite.org/about.html
- https://sqlite.org/copyright.html
- https://sqlite.org/withoutrowid.html

### Reuse decision: BZip2 development exports

SharpCompress was evaluated for direct .NET reading of Tatoeba `.bz2` exports. It supports modern .NET/BZip2 and is MIT-licensed, but it is not integrated because ingestion is development-only and Python's maintained standard-library `bz2`, `urllib.request`, TSV/text and hashing already solve the task without increasing shipped dependency surface.

References checked 2026-08-17:
- https://github.com/adamhathcock/sharpcompress
- https://www.nuget.org/packages/SharpCompress/
- https://docs.python.org/3/library/bz2.html
- https://docs.python.org/3/library/urllib.request.html

### SentencePack release rules

1. Preserve stable upstream sentence/translation IDs whenever supplied.
2. Preserve source, provenance and license metadata.
3. For CC BY material, retain per-sentence attribution and ship the required notice.
4. Never relabel CC BY material as CC0.
5. A CC0 EN-UA pair requires BOTH sentence IDs in their official language-specific CC0 exports.
6. Verify adjacent manifest SHA-256 before propagating license-specific provenance.
7. Do not reuse Tatoeba audio merely because text is reusable; audio licensing is contributor-specific.
8. Do not bundle another corpus/preprocessing/storage dependency until its license, provenance, runtime footprint and maintenance status are reviewed here.

Synthetic regression sentences are test-only data and are never presented as Tatoeba/human-verified corpus content.

## Oxford 5000 lexical QA provenance

Oxford Learner's Dictionaries is used as the authoritative sense/POS/CEFR reference for the Oxford-5000 additions QA. WordDeck does not copy Oxford definitions into the shipped dictionary; the QA process uses the official entries to select concise Ukrainian equivalents while preserving materially distinct POS/sense distinctions.

On 2026-08-18 the first extracted additions batch (`ox5000-add-0001` through `ox5000-add-0100`) received a source-backed second pass for every previously ambiguous row. The checked Oxford entries included `absorb`, `abuse`, `accent`, `accommodate`, `accordingly`, `acute`, `adhere`, `adjust`, `administer`, `admission`, `adoption`, `advocate`, `alert`, `alien`, `allegation`, `allege`, `allowance`, `altogether` and `apparatus`. This QA does not imply that the full additional 2,000-word Oxford-5000 set has been extracted or verified.

Official references checked 2026-08-18:
- https://www.oxfordlearnersdictionaries.com/
- individual Oxford Advanced Learner's Dictionary entries for the terms listed above

## British pronunciation generation provenance

British pronunciation generation is a development/build-time pipeline. The shipped runtime does **not** require Kokoro, Python, espeak-ng, a network service or an API; it only plays generated MP3 files resolved by stable dictionary/entry ID.

Reuse-first review retained the existing Kokoro generation path. The official `hexgrad/Kokoro-82M` model/repository declares Apache-2.0 and documents WordDeck's British voices `bf_emma` and `bm_george`. British English uses the existing Kokoro/Misaki `lang_code='b'` path with `en-gb` espeak-ng fallback, so that existing G2P path is the first choice for heteronym-specific pronunciation before another phoneme/NLP dependency is considered.

Official references checked 2026-08-17:
- https://huggingface.co/hexgrad/Kokoro-82M
- https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md
- https://github.com/hexgrad/kokoro

### Pronunciation override validation

`Audio/pronunciation-overrides.tsv` and `tools/validate_pronunciation_overrides.py` are WordDeck-specific development glue, not a new TTS/NLP subsystem. The validator uses Python standard-library components only to reconstruct the embedded Oxford source, enforce stable-ID/source-text drift checks and emit a targeted regeneration request.

The ledger does not guess heteronym pronunciations. Formatting-only/sense-marker normalization may be `ready`; entries whose pronunciation depends on lexical sense stay `review` until the existing British G2P/phonetic path or listening QA establishes the intended form.

The 2026-08-17 aggregate integrity audit of all seven existing Oxford 3000 generation artifacts is recorded in `Audio/OXFORD3000_AUDIO_INTEGRITY_QA_20260817.md`. It verified 3,308 unique stable-ID audio records with matching packaged byte sizes while separately identifying pronunciation-normalization work for sense markers, parenthetical labels, homographs and acronyms.
