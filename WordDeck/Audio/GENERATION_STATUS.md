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

This checkpoint verifies file count, manifest coverage, configured accent/speed/sample rate, voice distribution and nontrivial file sizes. It does not by itself assert human listening QA of every pronunciation. Homographs, acronyms, punctuation, multiword phrases and sense-marker overrides remain subject to pronunciation QA before final release.

## Next generation request

Continue with Oxford 3000 indexes 500–999 as the next 500-entry batch. Do not regenerate verified indexes 0–499 unless the TTS model, voices, pronunciation override rules, codec parameters or source text changes materially.
