# Oxford 3000 uppercase British-pronunciation QA — 2026-08-18

Branch: `worddeck-bootstrap` only.

## Scope

This checkpoint resolves the five uppercase/acronym candidates left by the aggregate Oxford 3000 audio audit. It does not claim the replacement MP3 artifact verified; generation output still has to be inspected after the targeted workflow completes.

## Existing generated records

The seven previously verified Oxford 3000 audio artifacts were re-inspected. The original manifests contain these exact records and pass the uppercase source text literally to TTS:

| Stable entry ID | Source | Original manifest audio_text | Original voice | Original MP3 bytes |
|---|---|---|---|---:|
| `oxford-a1-0129` | `CD` | `CD` | `bf_emma` | 8,685 |
| `oxford-a1-0224` | `DVD` | `DVD` | `bf_emma` | 11,373 |
| `oxford-a1-0541` | `OK` | `OK` | `bf_emma` | 7,917 |
| `oxford-a1-0820` | `TV` | `TV` | `bm_george` | 12,333 |
| `oxford-b1-0379` | `IT` | `IT` | `bf_emma` | 6,189 |

This proves the candidates are real stable dictionary entries and that the old generation path relied on uppercase grapheme heuristics rather than reviewed pronunciation data.

## Source-backed British pronunciations

Oxford Advanced Learner's Dictionary was checked on 2026-08-18:

- `CD`: BrE `/ˌsiː ˈdiː/` — https://www.oxfordlearnersdictionaries.com/definition/english/cd
- `DVD`: BrE `/ˌdiː viː ˈdiː/` — https://www.oxfordlearnersdictionaries.com/definition/english/dvd
- `IT`: BrE `/ˌaɪ ˈtiː/` for the information-technology noun — https://www.oxfordlearnersdictionaries.com/definition/english/it_2
- `OK`: BrE `/əʊˈkeɪ/` — https://www.oxfordlearnersdictionaries.com/definition/english/ok_1
- `TV`: BrE `/ˌtiː ˈviː/` — https://www.oxfordlearnersdictionaries.com/definition/english/tv

## Reuse-first implementation decision

No acronym expander, custom G2P, runtime pronunciation engine or new dependency was added.

The existing Apache-2.0 Kokoro/Misaki development-time path already supports reviewed raw phonemes through `generate_from_tokens()`. `CD`, `DVD`, `IT` and `TV` therefore use explicit reviewed Misaki phonemes. `OK` uses the unambiguous lexical spelling `okay`, allowing the same maintained British G2P path to produce the Oxford pronunciation.

Resolved ledger rows:

- `CD` -> `sˌiː dˈiː`
- `DVD` -> `dˌiː viː dˈiː`
- `IT` -> `ˌI tˈiː`
- `TV` -> `tˌiː vˈiː`
- `OK` -> text `okay`

The validator now fail-closes on the five exact stable IDs/source strings and requires them to be `ready`. The targeted regeneration request is 41 entries total: the already resolved 36 marker/sense entries plus these five uppercase entries.

## Release decision

**Uppercase source/pronunciation resolution: PASS.**

**Replacement audio artifact: NOT YET VERIFIED.**

Exact next step: inspect the 41-file targeted Actions artifact after generation, require exactly 41 stable IDs and manifest rows, confirm the five uppercase effective text/phoneme fields and expected voices, reject suspiciously small files, and record SHA-256/file-size evidence before replacing any original AudioPack member.
