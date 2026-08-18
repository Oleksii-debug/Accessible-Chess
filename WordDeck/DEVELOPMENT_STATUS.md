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

`tools/resolve_sentence_coverage_gaps.py` resolves all 188 IDs against the embedded Oxford TSV. Verified structural split:
- 114 ordinary single-surface entries that the current exact surface index can represent;
- 74 structurally outside the current single-surface index (sense markers, annotations, multiword or noncanonical hyphenated forms).

Blanket marker stripping remains forbidden because it would collapse semantically distinct records such as `can¹/can²`, `close¹/close²` and `wind¹/wind²`.

`tools/analyze_sentence_gap_occurrence.py` mirrors the production builder's bounded acceptance/matching rules: 2..24 normalized English tokens, apostrophe normalization, duplicate stable-pair rejection, exact ordinary-token matching and contiguous exact token-sequence matching for structurally safe phrase/hyphen candidates. It does not stem, lemmatize or collapse senses.

Checkpoint `6f79771cb023a7d37d6933e33ee741ff47afbf0e` adds `tools/summarize_sentence_gap_qa.py` plus production workflow integration. The summarizer is deterministic Python-standard-library QA glue only: it consumes the analyzer TSV, emits a durable `sentence-gap-summary.json`, records exact-present vs exact-absent ordinary IDs, safe phrase/hyphen evidence and protected unmeasured semantic rows, and explicitly limits any future morphology evaluation to ordinary exact-absent IDs. The full production artifact still needs inspection before its exact-present/exact-absent counts are promoted to a verified checkpoint.

Reuse-first morphology decision remains: do not invent a stemmer/lemmatizer. Current .NET inflection libraries surveyed are noun/plural-focused or abandoned and do not justify a runtime dependency; maintained spaCy remains acceptable only as development-time evidence if the production summary shows a meaningful exact-absent ordinary set. No morphology dependency is shipped or added.

## Oxford 5000

Embedded package remains 3,308 Oxford-3000 positions. Oxford-3000 semantic translation QA remains 240 reviewed / 208 verified / 32 needs-second-pass / 3,068 awaiting first pass.

Oxford-5000 additions extraction is incomplete. The first 100 extracted B2/C1 additions now have a completed source-backed second pass: all 100 rows are `verified`, with zero `needs_second_pass` or `pending` statuses in IDs `ox5000-add-0001` through `ox5000-add-0100`. The previously ambiguous 19 rows were checked against current Oxford Advanced Learner's Dictionary entries on 2026-08-18 with POS/sense distinctions retained in concise Ukrainian equivalents.

`tools/validate_oxford5000_additions_qa.py` is a fail-closed Python-standard-library CI validator for the staged ledger. It requires contiguous stable IDs for the first 100 rows, nonblank source/translation metadata, supported statuses and zero unresolved rows in that completed batch. It is development/CI glue only and adds no shipped runtime dependency. The Windows workflow now runs both its synthetic self-test and the real ledger validation.

This is a completed QA milestone only for the first extracted 100 additions, not for the full Oxford 5000. Oxford Learner's Dictionaries remains the authoritative extraction/sense reference; the remaining additional set is still unextracted/unverified and must not be claimed complete.

## British audio

Technical generation remains 3,308 / 3,308 with aggregate structural integrity green.

The 36 numbered/sense-marker candidates in `Audio/pronunciation-overrides.tsv` are now all source-resolved and marked `ready`: the original 19 formatting-only rows retain simple `audio_text` normalization, while the 17 former heteronym/sense-sensitive blockers now carry source-backed British Kokoro/Misaki raw-phoneme overrides. Oxford headword numbering/POS/pronunciation was checked on 2026-08-18; the detailed mapping is recorded in `Audio/OXFORD3000_HETERONYM_QA_20260818.md`.

Reuse-first decision: no custom homograph classifier or G2P was added. Existing Apache-2.0 Kokoro/Misaki development tooling is reused through Kokoro's supported `KPipeline.generate_from_tokens()` raw-phoneme path. `generate_british_audio.py` now selects that path only when a reviewed row supplies `phonemes`; ordinary generation is unchanged. `validate_pronunciation_overrides.py` fail-closes on unsupported British Misaki phoneme characters and requires exactly one of text or raw-phoneme override for every `ready` row. None of this changes WordDeck runtime dependencies.

The active targeted request is now exactly 36 numbered/sense-marker files. The new 36-file Actions artifact is **not yet promoted to verified** because this connector session cannot inspect the push-triggered Actions run/artifact directly. Do not claim regenerated audio complete until manifest/file inspection is available.

Uppercase `CD`, `DVD`, `IT`, `OK`, `TV` remain explicit QA candidates. Broader parenthetical/multiword listening QA also remains before final AudioPack release.

## Exact next steps

1. Inspect the new targeted 36-file pronunciation Actions result; validate all stable IDs, manifest `audio_text`/`phonemes`, nontrivial file sizes and intended voices before promoting the artifact.
2. Resolve the five uppercase candidates (`CD`, `DVD`, `IT`, `OK`, `TV`) using source IDs plus listening/phonetic evidence; do not assume letter-by-letter output without checking the generated path.
3. Inspect the production attributed SentencePack artifact from the classified-gap workflow; record real exact-present/exact-absent counts for the 114 ordinary gaps. Treat exact-present ordinary gaps as matcher/index QA, not morphology candidates.
4. Evaluate a maintained development-time lemmatizer only for the exact-absent ordinary SentencePack IDs if the measured set justifies it.
5. Continue Oxford-5000 extraction in substantial source-backed batches; the next content batch starts after `ox5000-add-0100`.
6. Continue Oxford-3000 semantic QA without blocking usable Recall/Spelling/Sentence slices.
7. Never modify `main`.
