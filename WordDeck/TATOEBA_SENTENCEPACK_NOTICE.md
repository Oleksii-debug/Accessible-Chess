# WordDeck Tatoeba SentencePack provenance notice

This notice applies to the Round-3 Tatoeba SentencePack evidence produced by WordDeck. Round 3 deliberately builds two different redistribution candidates so the release audit can distinguish a maximally conservative CC0 text subset from a practical attributed CC BY corpus.

## Candidate A — both-sides CC0 subset

`tools/worddeck/build_tatoeba_cc0_pairs.py` downloads the official Tatoeba per-language English and Ukrainian `sentences_CC0` exports plus the official English-Ukrainian links export.

A pair is eligible only when the English sentence ID is present in the official English CC0 sentence export, the Ukrainian sentence ID is present in the official Ukrainian CC0 sentence export, and the two IDs occur as a linked EN-UA pair in the official language-pair links export.

The generated manifest records upstream URLs, SHA-256 hashes and byte sizes, output SHA-256, counts and the exact selection rule. WordDeck independently verifies the adjacent manifest before accepting the pair TSV as a `CC0 1.0` text candidate.

The EN-UA relationship still comes from Tatoeba's links export. Tatoeba's downloads page states that the downloadable files are generally released under CC BY 2.0 FR and separately states that part of the sentence text is available under CC0. WordDeck therefore preserves the Tatoeba source/provenance notice and does not claim that the whole links dataset is CC0.

## Candidate B — attributed CC BY 2.0 FR corpus

`tools/worddeck/build_tatoeba_attributed_pairs.py` downloads the official detailed English and Ukrainian sentence exports and the official English-Ukrainian links export.

Tatoeba's downloads page describes the downloadable files as released under CC BY 2.0 FR. The detailed sentence export contains sentence ID, language, text and owner username. WordDeck accepts an attributed pair only when both detailed sentence rows are present, language-correct, linked by the official EN-UA links export, and both sides retain a nonblank owner username.

The generated attributed TSV carries both owner usernames beside the corresponding sentence IDs/text. The WordDeck builder embeds both attributions into each `SentenceRecord.Source`; the installation validator rejects an attributed Tatoeba pack if upstream IDs or per-side author markers are missing. Its adjacent manifest is fail-closed, records the upstream hashes/counts/selection rule, and declares exactly `CC BY 2.0 FR with BOTH sentence-owner usernames retained`.

This candidate is intended to test whether a practically useful EN-UA corpus can be produced while retaining record-level attribution. Independent release audit must review the generated manifest, attribution representation and this notice before public redistribution.

## No audio redistribution

Neither pipeline downloads or redistributes Tatoeba audio. Tatoeba audio has separate contributor-selected licensing and is outside this SentencePack evidence.

## Source

Tatoeba Project: https://tatoeba.org/
Official downloads and license statement: https://tatoeba.org/en/downloads
Official per-language exports: https://downloads.tatoeba.org/exports/per_language/
