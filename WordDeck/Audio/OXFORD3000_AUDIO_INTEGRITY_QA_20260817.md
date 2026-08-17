# Oxford 3000 British AudioPack integrity QA — 2026-08-17

Branch: `worddeck-bootstrap` only.

## Scope

This checkpoint audits the seven already-generated British-English Oxford 3000 Actions artifacts recorded in `Audio/GENERATION_STATUS.md`. It does not regenerate audio and does not claim pronunciation QA complete.

Verified generation artifacts cover indexes 0–3307 inclusive in seven batches: 500 + 500 + 500 + 500 + 500 + 500 + 308 = 3,308 positions.

## Structural integrity findings

All seven artifacts were downloaded and inspected as one aggregate set.

- MP3/manifest records inspected: **3,308**.
- Stable entry IDs: **3,308 unique / 3,308**.
- Generation indexes: **3,308 unique**, exact range **0–3307**.
- Manifest-declared byte sizes versus packaged MP3 byte sizes: **0 mismatches**.
- Accent metadata: **3,308 / 3,308 `en-GB`**.
- Speed metadata: **3,308 / 3,308 `1.0`**.
- Sample-rate target metadata: **3,308 / 3,308 `24000` Hz**.
- Voice distribution: `bf_emma` **1,675**, `bm_george` **1,633**.
- Smallest MP3: **4,077 bytes**; largest: **31,149 bytes**; mean approximately **9,843 bytes**.

This is sufficient evidence that the generated batches are structurally complete and internally coherent for packaging by stable entry ID. It is not evidence that every spoken form is linguistically correct.

## Pronunciation-content QA finding

The generation manifests show `audio_text == source` for **all 3,308 records**. Therefore no pronunciation-normalization or sense-marker override was applied during the completed generation batches.

That matters because the source dictionary deliberately contains sense numbers, parenthetical disambiguators, punctuation and homographs that should not necessarily be spoken literally. Final AudioPack release must therefore use a small deterministic development-time override map for the affected entries, regenerate only those entries, and re-run integrity checks. Wholesale regeneration of the other entries is not justified.

### Numbered/sense-marker candidates — 36

- `oxford-a1-0120` — `can¹`
- `oxford-a1-0150` — `close¹`
- `oxford-a1-0211` — `do¹`
- `oxford-a1-0422` — `last¹ (final)`
- `oxford-a1-0434` — `lie¹`
- `oxford-a1-0444` — `live¹`
- `oxford-a1-0446` — `long¹`
- `oxford-a1-0480` — `minute¹`
- `oxford-a1-0668` — `second¹ (next after the first)`
- `oxford-a1-0669` — `second¹ (unit of time)`
- `oxford-a2-0115` — `can²`
- `oxford-a2-0147` — `close²`
- `oxford-a2-0433` — `last¹ (final)`
- `oxford-a2-0434` — `last¹ (taking time)`
- `oxford-a2-0440` — `lead¹`
- `oxford-a2-0633` — `refuse¹`
- `oxford-a2-0652` — `ring¹`
- `oxford-a2-0653` — `ring²`
- `oxford-a2-0683` — `second¹ (next after the first)`
- `oxford-a2-0859` — `wind¹`
- `oxford-b1-0119` — `close²`
- `oxford-b1-0151` — `content¹`
- `oxford-b1-0396` — `lead¹`
- `oxford-b1-0404` — `lie² (tell a lie)`
- `oxford-b1-0410` — `live²`
- `oxford-b1-0506` — `plus¹`
- `oxford-b1-0608` — `ring²`
- `oxford-b1-0616` — `row¹`
- `oxford-b1-0768` — `used¹`
- `oxford-b1-0769` — `used²`
- `oxford-b2-0105` — `close¹`
- `oxford-b2-0468` — `pension¹`
- `oxford-b2-0481` — `plus¹`
- `oxford-b2-0655` — `tear¹`
- `oxford-b2-0656` — `tear²`
- `oxford-b2-0716` — `wind²`

### Upper-case/acronym candidates — 5

`CD`, `DVD`, `IT`, `OK`, `TV`.

These require explicit listening/phonetic QA because letter-by-letter versus lexicalized pronunciation is content-specific.

### Parenthetical/multiword candidates

The aggregate set contains **42 multiword source records**. Examples needing normalization review include `bank (money)`, `bank (river)`, `kind (type)`, `kind (caring)`, `light (from the sun/a lamp)`, `like (similar)`, `like (find sb/sth pleasant)`, `match (contest/correspond)`, `mine (hole in the ground)`, `race (...)`, `rest (...)`, `rock (...)`, `set (put)`, `set (group)`, `stick (...)`, `bear (animal)`, `bear (deal with)`, `used to`, `have to`, `ice cream`, `next to`, `no one`, `according to`, `all right`, `any more`, `per cent` and `a, an`.

Punctuation such as `old-fashioned`, `long-term` and `T-shirt` should be retained unless listening QA demonstrates a defect; punctuation alone is not a reason to override.

## Reuse/provenance decision

The existing generation path uses Kokoro with British voices `bf_emma` and `bm_george`. Reuse-first review on 2026-08-17 confirmed the official `hexgrad/Kokoro-82M` model card/repository declares Apache-2.0 licensing and documents these British voices. WordDeck runtime does not ship Kokoro/Python; generation is development-time only.

Before distribution of the final AudioPack, the release notices must retain model/generation provenance and relevant licenses. Generation-tool dependencies such as espeak-ng are not WordDeck runtime dependencies and must not be represented as such.

## Release decision

**Structural AudioPack integrity: PASS.**

**Pronunciation QA: NOT COMPLETE.**

Exact next step: add a deterministic development-time `source -> audio_text` override ledger for the high-risk entries, validate it with tests, regenerate only affected MP3s, then assemble one coherent AudioPack with a manifest containing stable entry ID, source text, effective audio text, voice, byte size and SHA-256 for every file.