# WordDeck third-party data notices

## Sentence Coach corpus pipeline

WordDeck does not currently bundle a production sentence corpus. The approved first development-time source candidate for the EN-UA SentencePack pipeline is Tatoeba sentence-pair data.

Tatoeba's official downloads page states that its downloadable text files are released under Creative Commons Attribution 2.0 France (CC BY 2.0 FR), with part of the sentence collection additionally available under CC0 1.0. The official Terms of Use likewise state that textual sentences use CC BY 2.0 FR by default and that attribution is required.

Official references checked 2026-08-17:
- https://tatoeba.org/en/downloads
- https://tatoeba.org/en/terms_of_use
- https://downloads.tatoeba.org/exports/
- https://downloads.tatoeba.org/exports/per_language/eng/

The official export index exposes per-language weekly files including `eng_sentences_CC0.tsv.bz2` and `eng-ukr_links.tsv.bz2`. A real distributable EN-UA pack must still prove that both sentence sides used for each pair belong to the chosen license subset before the pack is labelled CC0.

### Reuse decision: JSON/install layer

Runtime SentencePack validation, serialization, installation and loading use the .NET standard library (`System.Text.Json` plus `System.IO`). No third-party dependency is needed for this small deterministic layer, which keeps the shipped Windows application self-contained and reduces attack/runtime surface.

### Reuse decision: BZip2 development exports

SharpCompress was evaluated on 2026-08-17 for direct development-time reading of Tatoeba `.bz2` exports. Its official project supports .NET 8 and BZip2 and is MIT-licensed; current NuGet releases are actively maintained. It is not integrated yet because WordDeck already accepts an uncompressed EN-UA pair TSV and adding a multi-format compression dependency to the shipped executable solely for a development ingestion convenience would increase footprint unnecessarily. If direct `.bz2` ingestion becomes necessary, prefer isolating SharpCompress in a development-only tool/project rather than making it a runtime requirement.

References checked 2026-08-17:
- https://github.com/adamhathcock/sharpcompress
- https://www.nuget.org/packages/SharpCompress/

Release rules for WordDeck SentencePacks:
1. Preserve stable upstream sentence/translation IDs whenever the selected export supplies them.
2. Store `source`, `provenance`, and `license` metadata in every SentencePack/record.
3. If a pack contains CC BY 2.0 FR material, ship the required attribution and license notice with the pack/application.
4. Prefer the CC0 subset when it provides adequate EN-UA coverage because it simplifies redistribution, but do not silently relabel CC BY material as CC0.
5. Do not reuse Tatoeba audio merely because the sentence text is reusable. Tatoeba audio has contributor-specific licensing and must be evaluated independently.
6. Do not bundle any other corpus or preprocessing library until its redistribution license is reviewed and recorded here.

Synthetic regression sentences used only in source-code self-tests are marked as synthetic test data and are not presented as Tatoeba or human-verified corpus content.
