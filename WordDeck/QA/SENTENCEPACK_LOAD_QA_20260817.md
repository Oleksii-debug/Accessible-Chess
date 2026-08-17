# SentencePack runtime/storage QA — 2026-08-17

Branch: `worddeck-bootstrap` only.

## Tested production corpus

Attributed Tatoeba EN-UA SentencePack:

- Pack ID: `tatoeba-en-uk-ccby-20260817`
- License: `CC BY 2.0 FR`
- Sentences: 207,578
- Indexed current Oxford entry IDs: 3,120 / 3,308
- raw JSON: 245,812,867 bytes
- gzip interchange package: 19,906,945 bytes

## Eager JSON/GZIP baseline

The diagnostic path uses the exact runtime `SentencePackIo.Read` path, including validation and construction of the in-memory entry/lemma indexes used by Sentence Coach.

Verified Windows Actions measurements are in the same range across production runs. The original checkpoint was:

- load + validation/index construction: 5,303 ms
- managed-memory delta: 543,390,448 bytes
- process working-set delta: 628,666,368 bytes

The compact-schema comparison run `32054968152` measured the same 207,578-record gzip at:

- 5,175 ms
- managed-memory delta: 543,569,744 bytes
- working-set delta: 624,680,960 bytes

Conclusion: gzip solves distribution size, but eager materialization remains unsuitable for the large production corpus.

## Reuse-first SQLite prototype

`Microsoft.Data.Sqlite` 8.0.29 is pinned for the measured prototype. SQLite is used as a serverless, read-only indexed local store; JSON/GZIP remains the interchange/import format.

The first proof schema stored a serialized full `SentenceRecord` JSON payload per row and duplicated string target IDs in the many-to-many index. On production data it proved the read/query concept but produced a 341,766,144-byte database. A fresh-process one-target query returned 1,141 records in 101 ms with +3,117,584 managed bytes and +27,217,920 working-set bytes.

Schema v2 removes the duplicated full JSON payload, dictionary-encodes target IDs to integers, stores CEFR values compactly, reconstructs canonical tokens from English text, stores lemma overrides only when they differ from tokens, and uses `WITHOUT ROWID` only for compact composite-key tables where the SQLite design is appropriate.

Production workflow run `32054968152`, commit `858efb143ba5a9c4a0c5dccfb41de10de07af5c5`, verified:

- SQLite database: **72,400,896 bytes**
- reduction from prototype v1: **269,365,248 bytes (78.8%)**
- build/conversion time after eager source load: 10,183 ms
- representative one-target result count: 1,141
- fresh-process query: **158 ms**
- fresh-process managed-memory delta: **2,172,960 bytes**
- fresh-process working-set delta: **24,375,296 bytes**

Compared with the same run's eager working-set delta, the disk-backed query path uses about **96.1% less incremental working set** for the representative query. The query returns complete `SentenceRecord` data needed by current ranking/evaluation, including all target IDs and per-target CEFR levels.

## Decision

The disk-backed SQLite approach has now demonstrated a material runtime-memory win while preserving offline/single-file corpus behavior. The 72.4 MB database is larger than the 19.9 MB gzip interchange file but is practical enough to continue to the smallest runtime integration rather than inventing a custom binary/index format.

Next implementation step: keep `.json`/`.json.gz` backwards-compatible for import/interchange, build/store the SQLite representation at installation time, and make Sentence Coach query candidates on demand without eagerly loading all 207,578 records. Add migration/import/recovery tests before treating SQLite as the default installed runtime representation.
