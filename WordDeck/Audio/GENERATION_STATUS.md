# WordDeck British audio generation status

This file is the durable checkpoint for offline pronunciation generation on `worddeck-bootstrap`.

## Verified Oxford 3000 generation batches

| Indexes | Count | Workflow run | Artifact | Artifact id | Digest | Status |
|---|---:|---:|---|---:|---|---|
| 0–499 | 500 | `31969355104` | `worddeck-oxford3000-en-gb-0-500` | `9269496494` | `sha256:23d18d26b888dc8491af045ae1179c18f16c9b1d030e5bd7a267229464fc6a6d` | VERIFIED_GENERATION_OUTPUT |
| 500–999 | 500 | `31975457181` | `worddeck-oxford3000-en-gb-500-500` | `9271048958` | `sha256:f7f451f1eb907d1dc43fbb47f374e44572b4bdb0df7fd0680bd2b8e9fed840ab` | VERIFIED_GENERATION_OUTPUT |
| 1000–1499 | 500 | `31978380730` | `worddeck-oxford3000-en-gb-1000-500` | `9271815418` | `sha256:a083fa66cd48208a7e1367e01c33ae57624a9876ef8d469abc799a9b8e54187d` | VERIFIED_GENERATION_OUTPUT |
| 1500–1999 | 500 | `31981023256` | `worddeck-oxford3000-en-gb-1500-500` | `9272509641` | `sha256:1805edd67330c4460ddfd9befb91ef0d553e4d04f69393cc91570c4bbc02417f` | VERIFIED_GENERATION_OUTPUT |
| 2000–2499 | 500 | `31983937072` | `worddeck-oxford3000-en-gb-2000-500` | `9273349615` | `sha256:8ac7c555fcab6d347c8d1fea63181509f3036cc38be9acb2535d7b59a525a378` | VERIFIED_GENERATION_OUTPUT |
| 2500–2999 | 500 | `31986850216` | `worddeck-oxford3000-en-gb-2500-500` | `9274213466` | `sha256:fe71c5e8bfc20c3e41381afb0c8d8d998268f8122b55e87ceec60e5c399b3eeb` | VERIFIED_GENERATION_OUTPUT |
| 3000–3307 | 308 | `31989974909` | `worddeck-oxford3000-en-gb-3000-308` | `9275121150` | `sha256:da1a656ad406abef911a88b358f265f1a665b280bc130924995cf8414c8e5ee2` | VERIFIED_GENERATION_OUTPUT |

## Final Oxford 3000 batch verification

Workflow run `31989974909` completed successfully on commit `c9c2e71527bf500c79b3d17e70a1ab7abba48f71`.

- Requested source: `oxford3000`
- Requested indexes: 3000–3307 inclusive
- Requested count: 308
- Generator reported: `Generated 308 new files`
- Workflow validation reported: `Generated 308 audio files; requested up to 308`
- Validation rejected files at or below 512 bytes; no such failure occurred.
- Manifest file was required to be non-empty; validation passed.
- Accent/configuration remains British English `en-GB` with voices `bf_emma` and `bm_george`, speed `1.0`, MP3, 24 kHz generation target.
- Artifact upload completed successfully at 3,003,299 bytes with the digest recorded above.

## Aggregate verified generation coverage

- Oxford 3000 verified generated positions: **3,308 / 3,308**.
- Verified index range: **0–3307 inclusive**.
- Status: **OXFORD_3000_GENERATION_COMPLETE**.
- Do not regenerate these ranges unless the source text, TTS model, voices, pronunciation override rules, codec parameters, or a pronunciation QA finding changes materially.

## Release caveat

Generation completeness is not the same as pronunciation QA completeness. The generation checks establish batch coverage, non-empty output, manifest creation, configured British voices/speed/format and successful packaging. Homographs, abbreviations, acronyms, punctuation, multiword phrases and numbered sense markers still require pronunciation QA/override review before final release. Examples in the final batch that deserve explicit sense-marker review include `pension¹`, `plus¹`, `tear¹`, `tear²` and `wind²`.

## Next audio work

Do **not** schedule another Oxford 3000 generation batch. Resume audio generation only after the combined Oxford 5000 source is reconciled and verified enough to identify the additional entries safely. Until then, prioritize dynamic deck implementation, Oxford 5000 extraction/translation QA, and pronunciation-override infrastructure.
