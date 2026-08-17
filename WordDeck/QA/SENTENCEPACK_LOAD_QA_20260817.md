# SentencePack runtime load QA — 2026-08-17

Branch: `worddeck-bootstrap` only.

## Tested artifact

Attributed Tatoeba EN-UA SentencePack produced by workflow run `32048719259` from the current production pipeline.

- Pack ID: `tatoeba-en-uk-ccby-20260817`
- License: `CC BY 2.0 FR`
- Sentences: 207,578
- Indexed current Oxford entry IDs: 3,120 / 3,308
- gzip file size: 19,906,945 bytes
- raw JSON size: 245,812,867 bytes

## Measurement path

`WordDeck.exe --measure-sentence-pack <pack.json.gz> <report.json>` uses only built-in .NET diagnostics (`System.Diagnostics.Stopwatch`, `Process.WorkingSet64`, `GC.GetTotalMemory`) and the exact runtime `SentencePackIo.Read` path. `SentencePack.Validate()` builds the same in-memory entry/lemma indexes used by Sentence Coach before the after-sample is taken.

Windows Actions measurement on the real pack:

- elapsed load + validation/index construction: **5,303 ms**;
- managed bytes before: 115,440;
- managed bytes after: 543,505,888;
- managed delta: **543,390,448 bytes**;
- process working set before: 24,154,112 bytes;
- process working set after: 652,820,480 bytes;
- working-set delta: **628,666,368 bytes**.

The workflow asserts the measured sentence count (207,578), persists `load-diagnostics.json`, and uploads it with the corpus artifact.

## Decision

The gzip distribution size is acceptable, but eagerly materializing the full corpus plus duplicate in-memory indexes is not. A ~629 MB working-set increase is now a demonstrated runtime problem, so further optimization is justified.

Reuse-first review therefore moves disk-backed/lazy indexed storage ahead of custom streaming/container formats. The leading candidate is SQLite accessed through Microsoft's maintained `Microsoft.Data.Sqlite` ADO.NET provider: SQLite is serverless, single-file and public-domain; Microsoft.Data.Sqlite is maintained in the .NET/EF Core repository under MIT and can be used without Entity Framework. No SQLite package has been added to WordDeck yet; next work must prototype and measure a read-only indexed SentencePack representation before committing to the dependency.

The existing `.json`/`.json.gz` schema remains the interchange/import format until a measured replacement path is proven. Do not remove backwards compatibility based on this benchmark alone.
