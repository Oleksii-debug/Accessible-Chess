# WordDeck British audio generation status

This file is the durable checkpoint for offline pronunciation generation on `worddeck-bootstrap`.

## Verified batches

### Oxford 3000 — entries 0–499

- Workflow run: `31969355104`
- GitHub artifact: `worddeck-oxford3000-en-gb-0-500`
- Artifact id: `9269496494`
- Artifact digest: `sha256:23d18d26b888dc8491af045ae1179c18f16c9b1d030e5bd7a267229464fc6a6d`
- Artifact container size: 4,589,442 bytes
- Inner archive inspected after download.
- MP3 files: exactly 500
- Manifest records: exactly 500, indexes 0 through 499
- Smallest MP3: 4,845 bytes
- Largest MP3: 31,149 bytes
- Mean MP3 size: 9,338.2 bytes
- Files at or below 512 bytes: 0
- Accent: `en-GB` for all 500 manifest records
- Speed: `1.0` for all 500 manifest records
- Sample rate: `24000` Hz for all 500 manifest records
- Voices: `bf_emma` 245 files; `bm_george` 255 files
- First entry: `oxford-a1-0001` — `a, an`
- Last entry: `oxford-a1-0500` — `museum`
- Status: `VERIFIED_GENERATION_OUTPUT`

### Oxford 3000 — entries 500–999

- Workflow run: `31975457181`
- GitHub artifact: `worddeck-oxford3000-en-gb-500-500`
- Artifact id: `9271048958`
- Artifact digest: `sha256:f7f451f1eb907d1dc43fbb47f374e44572b4bdb0df7fd0680bd2b8e9fed840ab`
- Artifact container size: 4,552,936 bytes
- Inner archive inspected after download.
- MP3 files: exactly 500
- Manifest records: exactly 500, indexes 500 through 999
- Smallest MP3: 4,077 bytes
- Largest MP3: 23,085 bytes
- Median MP3 size: 8,877 bytes
- Files below 512 bytes: 0
- Accent: `en-GB` for all 500 manifest records
- Speed: `1.0` for all 500 manifest records
- Sample rate: `24000` Hz for all 500 manifest records
- Voices: `bf_emma` 262 files; `bm_george` 238 files
- Missing manifest-referenced audio files: 0
- Duplicate manifest entry IDs: 0
- Status: `VERIFIED_GENERATION_OUTPUT`

### Oxford 3000 — entries 1000–1499

- Workflow run: `31978380730`
- GitHub artifact: `worddeck-oxford3000-en-gb-1000-500`
- Artifact id: `9271815418`
- Artifact digest: `sha256:a083fa66cd48208a7e1367e01c33ae57624a9876ef8d469abc799a9b8e54187d`
- Artifact container size: 4,836,749 bytes
- Inner archive inspected after download.
- MP3 files: exactly 500
- Manifest records: exactly 500, indexes 1000 through 1499
- Smallest MP3: 5,805 bytes
- Largest MP3: 20,589 bytes
- Files at or below 512 bytes: 0
- Accent: `en-GB` for all 500 manifest records
- Speed: `1.0` for all 500 manifest records
- Sample rate: `24000` Hz for all 500 manifest records
- Voices: `bf_emma` 261 files; `bm_george` 239 files
- Missing manifest-referenced audio files: 0
- Duplicate manifest entry IDs: 0
- Status: `VERIFIED_GENERATION_OUTPUT`

### Oxford 3000 — entries 1500–1999

- Workflow run: `31981023256`
- GitHub artifact: `worddeck-oxford3000-en-gb-1500-500`
- Artifact id: `9272509641`
- Artifact digest: `sha256:1805edd67330c4460ddfd9befb91ef0d553e4d04f69393cc91570c4bbc02417f`
- Artifact container size: 4,947,862 bytes
- Inner archive inspected after download.
- MP3 files: exactly 500
- Manifest records: exactly 500, indexes 1500 through 1999
- Smallest MP3: 5,997 bytes
- Largest MP3: 23,085 bytes
- Files at or below 512 bytes: 0
- Accent: `en-GB` for all 500 manifest records
- Speed: `1.0` for all 500 manifest records
- Sample rate: `24000` Hz for all 500 manifest records
- Voices: `bf_emma` 239 files; `bm_george` 261 files
- Missing manifest-referenced audio files: 0
- Duplicate manifest entry IDs: 0
- Status: `VERIFIED_GENERATION_OUTPUT`

### Oxford 3000 — entries 2000–2499

- Workflow run: `31983937072`
- GitHub artifact: `worddeck-oxford3000-en-gb-2000-500`
- Artifact id: `9273349615`
- Artifact digest: `sha256:8ac7c555fcab6d347c8d1fea63181509f3036cc38be9acb2535d7b59a525a378`
- Artifact container size: 5,030,175 bytes
- Inner archive inspected after download.
- MP3 files: exactly 500
- Manifest records: exactly 500, indexes 2000 through 2499
- Smallest MP3: 5,805 bytes
- Largest MP3: 31,149 bytes
- Files at or below 512 bytes: 0
- Accent: `en-GB` for all 500 manifest records
- Speed: `1.0` for all 500 manifest records
- Sample rate: `24000` Hz for all 500 manifest records
- Voices: `bf_emma` 247 files; `bm_george` 253 files
- Missing manifest-referenced audio files: 0
- Duplicate manifest entry IDs: 0
- Status: `VERIFIED_GENERATION_OUTPUT`

### Oxford 3000 — entries 2500–2999

- Workflow run: `31986850216`
- GitHub artifact: `worddeck-oxford3000-en-gb-2500-500`
- Artifact id: `9274213466`
- Artifact digest: `sha256:fe71c5e8bfc20c3e41381afb0c8d8d998268f8122b55e87ceec60e5c399b3eeb`
- Artifact container size: 5,039,498 bytes
- Inner archive inspected after download.
- MP3 files: exactly 500
- Manifest records: exactly 500, indexes 2500 through 2999
- Smallest MP3: 5,997 bytes
- Largest MP3: 17,325 bytes
- Files at or below 512 bytes: 0
- Accent: `en-GB` for all 500 manifest records
- Speed: `1.0` for all 500 manifest records
- Sample rate: `24000` Hz for all 500 manifest records
- Voices: `bf_emma` 260 files; `bm_george` 240 files
- Missing manifest-referenced audio files: 0
- Duplicate manifest entry IDs: 0
- Status: `VERIFIED_GENERATION_OUTPUT`

The checkpoints above verify file count, manifest coverage, configured accent/speed/sample rate, voice distribution, ID uniqueness and nontrivial file sizes. They do not by themselves assert human listening QA of every pronunciation. Homographs, acronyms, punctuation, multiword phrases and sense-marker overrides remain subject to pronunciation QA before final release.

## Aggregate verified generation coverage

- Oxford 3000 verified generated entries: 3,000 / 3,308 currently embedded positions.
- Verified index range: 0–2999 inclusive.
- No verified range should be regenerated unless the TTS model, voices, pronunciation override rules, codec parameters or source text changes materially.

## Next generation request

Continue with Oxford 3000 indexes 3000–3307 as the final 308-entry batch for the currently embedded Oxford 3000 source.
