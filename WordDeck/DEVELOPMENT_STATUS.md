# WordDeck development checkpoint

Last updated: 2026-08-18
Branch: `worddeck-bootstrap` only. Never develop WordDeck on `main`.

## Verified product baseline

Recall remains green: five permanent renameable core decks plus user decks, stable IDs/shortcuts, no-repeat shuffle bag, custom cards, autosave/backup/current-card recovery, Ctrl+S and optional offline British pronunciation.

Spelling remains an independent persisted track with five core plus user decks, exact native-TextBox spelling, wrong-answer lock, required correct typing after hints, objective stats, conservative offline coach moves only among core spelling decks, undo/explanations and rebindable persisted commands.

Sentence Spelling remains green with installed pack selection, spelling-deck scope, 1- or 2-target exercises, Ukrainian prompt, native English TextBox, Enter submit, token/form multiset evaluation with word order intentionally ignored, concise error diagnosis, required correct typing after Show Answer, persisted stats/recent/current exercise and same-scope two-target intersections.

Do not claim NVDA verification until the user tests an actual Windows build with NVDA.

## SentencePack corpus/runtime

Strict both-side Tatoeba CC0 is too small for primary use: 2 EN-UA pairs / 11 current Oxford IDs.

Attributed Tatoeba `CC BY 2.0 FR` production pack remains 207,578 EN-UA sentences, 3,120 / 3,308 Oxford IDs covered, 190,315 sentences with >=2 indexed targets, 160,058 with >=3, 53,612 quality-flagged, and 0 accepted records missing per-side author attribution.

Portable interchange remains JSON/GZIP (~245.8 MB raw / ~19.9 MB gzip). Installed runtime prefers schema-v2 SQLite (~72.4 MB) through maintained MIT-licensed `Microsoft.Data.Sqlite` 8.0.29; SQLite remains local/serverless/offline. No runtime Python/Java/API/server was added.

Verified full-corpus benchmark after batched SQLite scope coverage: metadata open 79 ms; 1-target coverage 33 ms (3,120 IDs); 2-target same-scope coverage 56 ms (3,114 IDs); representative 1-target query 179 ms; 2-target intersection 13 ms; measured diagnostic delta ~49.9 MB working set. Previous eager/repeated-query path took ~64.7 seconds for full-scope coverage.

Windows run `32065274229` and attributed SentencePack run `32065274247` on `c6e166046167c6596be23515e47c11d8c8dac15d` were fully green.

## Sentence coverage gaps

Production pack still has exactly 188 current Oxford IDs without a `TargetEntryId`: A1 23, A2 35, B1 54, B2 76. Source list: `QA/sentence_coverage_gaps_20260817.txt`.

`tools/resolve_sentence_coverage_gaps.py` resolves all 188 IDs against the embedded Oxford TSV. Verified structural split: 114 ordinary single-surface entries that the current exact surface index can represent; 74 structurally outside the current single-surface index (sense markers, annotations, multiword or noncanonical hyphenated forms).

Blanket marker stripping remains forbidden because it would collapse semantically distinct records such as `can¹/can²`, `close¹/close²` and `wind¹/wind²`.

`tools/analyze_sentence_gap_occurrence.py` mirrors the production builder's bounded acceptance/matching rules. `tools/summarize_sentence_gap_qa.py` emits a deterministic production summary of exact-present/exact-absent ordinary IDs, safe phrase/hyphen evidence and protected semantic rows.

Reuse-first morphology decision remains: do not invent a stemmer/lemmatizer. Current .NET inflection libraries surveyed are noun/plural-focused or abandoned and do not justify a runtime dependency; maintained spaCy remains acceptable only as development-time evidence if the production summary shows a meaningful exact-absent ordinary set. No morphology dependency is shipped or added.

## Oxford 5000

Embedded package remains 3,308 Oxford-3000 positions. Oxford-3000 semantic translation QA remains 240 reviewed / 208 verified / 32 needs-second-pass / 3,068 awaiting first pass.

Oxford-5000 additions extraction is incomplete. The first 100 extracted B2/C1 additions have a completed source-backed second pass: all 100 rows are `verified`, with zero unresolved statuses in IDs `ox5000-add-0001` through `ox5000-add-0100`. The previously ambiguous rows were checked against current Oxford Advanced Learner's Dictionary entries on 2026-08-18 with POS/sense distinctions retained in concise Ukrainian equivalents.

`tools/validate_oxford5000_additions_qa.py` remains the fail-closed CI validator for the staged ledger. Full Oxford 5000 completion must not be claimed until the remaining additions are extracted, translated and semantically checked.

## British audio

Technical Oxford 3000 generation remains 3,308 / 3,308 with aggregate structural integrity green.

The 36 numbered/sense-marker candidates remain source-resolved and `ready`; 17 pronunciation-sensitive rows use reviewed British Kokoro/Misaki raw-phoneme overrides. No custom homograph classifier/G2P was introduced: existing Apache-2.0 Kokoro/Misaki development tooling is reused through `generate_from_tokens()`. WordDeck runtime remains unchanged and does not require Kokoro/Python.

The five uppercase candidates are now also source-resolved and represented by exact stable IDs in `Audio/pronunciation-overrides.tsv`:
- `oxford-a1-0129` `CD` -> Oxford BrE /ˌsiː ˈdiː/;
- `oxford-a1-0224` `DVD` -> /ˌdiː viː ˈdiː/;
- `oxford-a1-0541` `OK` -> /əʊˈkeɪ/;
- `oxford-a1-0820` `TV` -> /ˌtiː ˈviː/;
- `oxford-b1-0379` `IT` -> /ˌaɪ ˈtiː/ for information technology.

The original seven manifests were re-inspected and confirmed that all five old files used literal uppercase `audio_text == source`; exact old file/voice evidence and authoritative Oxford links are recorded in `Audio/OXFORD3000_UPPERCASE_QA_20260818.md`.

Reuse-first decision: no acronym parser or pronunciation subsystem was added. `CD`, `DVD`, `IT` and `TV` use reviewed raw Misaki phonemes; `OK` uses unambiguous lexical `okay` through the existing British G2P path. The validator now fail-closes on all 41 exact candidates (36 marker/sense + 5 uppercase), and `Audio/generation-request.json` requests targeted regeneration of all 41.

**Uppercase source/pronunciation resolution is verified. Replacement MP3 output is not yet promoted to verified.** Do not claim the 41-file targeted regeneration complete until its Actions artifact/manifest is inspected.

Broader parenthetical/multiword listening QA remains before final AudioPack release.

## Exact next steps

1. Inspect the new 41-file pronunciation Actions result; require exactly 41 stable IDs/manifest rows, verify the five uppercase effective text/phoneme fields, voices, nontrivial sizes and hashes before promoting replacement audio.
2. Inspect the production attributed SentencePack gap-summary artifact and record exact-present/exact-absent counts for the 114 ordinary gaps. Treat exact-present ordinary gaps as matcher/index QA, not morphology candidates.
3. Evaluate a maintained development-time lemmatizer only for the exact-absent ordinary SentencePack IDs if the measured set justifies it.
4. Continue Oxford-5000 extraction after `ox5000-add-0100` in substantial source-backed batches; do not infer additions by guesswork.
5. Continue Oxford-3000 semantic QA without blocking usable Recall/Spelling/Sentence slices.
6. Continue broader AudioPack parenthetical/multiword QA and assemble the stable-ID final pack only after targeted replacements are verified.
7. Never modify `main`.
