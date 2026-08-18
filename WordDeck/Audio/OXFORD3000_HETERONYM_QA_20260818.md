# Oxford 3000 British heteronym QA — 2026-08-18

Branch: `worddeck-bootstrap` only.

## Scope and decision

This checkpoint resolves the 17 sense-sensitive rows that were deliberately held as `review` in `Audio/pronunciation-overrides.tsv`. It does not claim the five all-uppercase candidates or broader multiword listening QA complete.

The lexical decision is source-backed: Oxford Advanced Learner's Dictionary headword numbering, part of speech and British pronunciation were used to map each numbered WordDeck source record to the intended British pronunciation. WordDeck does not copy dictionary definitions; the external source is used only to select the intended pronunciation for the existing headword/sense record.

## Reuse-first implementation

No custom G2P, homograph classifier or runtime NLP component was added. The existing development-time Kokoro/Misaki path is retained. Kokoro's maintained `KPipeline.generate_from_tokens()` API accepts a raw phoneme string, and Misaki documents the British-English phoneme inventory used by Kokoro. The generator now uses this supported path only when a reviewed ledger row supplies `phonemes`; ordinary rows continue through the existing British G2P path.

This remains development/build tooling only. WordDeck runtime is still self-contained/offline .NET and only plays generated audio files.

References checked 2026-08-18:
- https://github.com/hexgrad/kokoro/blob/main/kokoro/pipeline.py
- https://github.com/hexgrad/kokoro/blob/main/examples/phoneme_example.py
- https://github.com/hexgrad/misaki/blob/main/EN_PHONES.md
- https://github.com/hexgrad/misaki

## Resolved mappings

The 17 previously blocked records are now generation-ready:

- `oxford-a1-0150` `close¹`: Oxford `close1` verb, BrE /kləʊz/ -> Misaki `klˈQz`.
- `oxford-a1-0444` `live¹`: Oxford `live1` verb, BrE /lɪv/ -> `lˈɪv`.
- `oxford-a2-0147` `close²`: Oxford `close2` adjective, BrE /kləʊs/ -> `klˈQs`.
- `oxford-a2-0440` `lead¹`: Oxford `lead1` verb, BrE /liːd/ -> `lˈiːd`.
- `oxford-a2-0633` `refuse¹`: Oxford `refuse1` verb, BrE /rɪˈfjuːz/ -> `ɹɪfjˈuːz`.
- `oxford-a2-0859` `wind¹`: Oxford `wind1` noun, BrE /wɪnd/ -> `wˈɪnd`.
- `oxford-b1-0119` `close²`: Oxford `close2` adverb/adjective pronunciation, BrE /kləʊs/ -> `klˈQs`.
- `oxford-b1-0151` `content¹`: Oxford `content1` noun, BrE /ˈkɒntent/ -> `kˈɒntɛnt`.
- `oxford-b1-0396` `lead¹`: Oxford `lead1` noun, BrE /liːd/ -> `lˈiːd`.
- `oxford-b1-0410` `live²`: Oxford `live2` adjective/adverb, BrE /laɪv/ -> `lˈIv`.
- `oxford-b1-0616` `row¹`: Oxford `row1` noun (line/arrangement), BrE /rəʊ/ -> `ɹˈQ`.
- `oxford-b1-0768` `used¹`: Oxford `used1` adjective (accustomed), BrE /juːst/ -> `jˈuːst`.
- `oxford-b1-0769` `used²`: Oxford `used2` adjective (previously used), BrE /juːzd/ -> `jˈuːzd`.
- `oxford-b2-0105` `close¹`: Oxford `close1` noun, BrE /kləʊz/ -> `klˈQz`.
- `oxford-b2-0655` `tear¹`: Oxford `tear1` noun/verb (rip), BrE /teə(r)/ -> British Misaki `tˈɛː`.
- `oxford-b2-0656` `tear²`: Oxford `tear2` noun/verb (eye liquid), BrE /tɪə(r)/ -> `tˈɪə`.
- `oxford-b2-0716` `wind²`: Oxford `wind2` verb, BrE /waɪnd/ -> `wˈInd`.

Oxford references checked 2026-08-18 include the corresponding `close1`, `close2`, `live1`, `live2`, `lead1`, `refuse1`, `content1`, `row1`, `used1`, `used2`, `wind1`, `wind2`, `tear1` and `tear2` entries at https://www.oxfordlearnersdictionaries.com/.

## Validation rules added

`tools/validate_pronunciation_overrides.py` now accepts a final optional `phonemes` column while remaining backwards-compatible with the old five-column ledger during migration. A `ready` row must define exactly one of `audio_text` or `phonemes`; a `review` row must define neither. Raw phonemes fail closed if they contain characters outside Misaki's documented British-English model vocabulary or exceed Kokoro's raw-phoneme length limit.

`tools/generate_british_audio.py` records the effective raw phonemes in `manifest.jsonl` when used. Existing text-only normalization remains unchanged.

## Current release state

All 36 numbered/sense-marker candidates are now marked `ready`: 19 text-normalization overrides plus 17 source-backed raw-phoneme overrides. A targeted generation request for all 36 has been queued by repository state.

This checkpoint does **not** promote the regenerated MP3 artifact to verified. The new 36-file Actions result still requires artifact/manifest inspection, and the five uppercase candidates (`CD`, `DVD`, `IT`, `OK`, `TV`) remain explicit pronunciation/listening QA items before AudioPack completion.
