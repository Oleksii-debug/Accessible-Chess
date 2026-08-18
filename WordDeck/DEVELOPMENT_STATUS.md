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

`tools/analyze_sentence_gap_occurrence.py` now mirrors the production builder's bounded acceptance/matching rules: 2..24 normalized English tokens, apostrophe normalization, duplicate stable-pair rejection, exact ordinary-token matching and contiguous exact token-sequence matching for structurally safe phrase/hyphen candidates. It does not stem, lemmatize or collapse senses.

Checkpoint `6f79771cb023a7d37d6933e33ee741ff47afbf0e` adds `tools/summarize_sentence_gap_qa.py` plus production workflow integration. The summarizer is deterministic Python-standard-library QA glue only: it consumes the analyzer TSV, emits a durable `sentence-gap-summary.json`, records exact-present vs exact-absent ordinary IDs, safe phrase/hyphen evidence and protected unmeasured semantic rows, and explicitly limits any future morphology evaluation to ordinary exact-absent IDs. Its synthetic self-test has been checked locally; the full production Actions result for this checkpoint is not yet marked verified here until the new artifact is inspected.

Reuse-first morphology decision remains: do not invent a stemmer/lemmatizer. Current .NET inflection libraries surveyed are noun/plural-focused or abandoned and do not justify a runtime dependency; maintained spaCy remains acceptable only as development-time evidence if the production summary shows a meaningful exact-absent ordinary set. No morphology dependency is shipped or added.

## Oxford 5000

Embedded package remains 3,308 Oxford-3000 positions. Oxford-3000 semantic translation QA remains 240 reviewed / 208 verified / 32 needs-second-pass / 3,068 awaiting first pass.

Oxford-5000 additions extraction is incomplete. First 100 extracted B2/C1 additions have Ukrainian translations; ambiguous/polysemous/multi-POS records remain `needs_second_pass`. Oxford Learner's Dictionaries remains the authoritative extraction reference; its official description confirms Oxford 5000 = Oxford 3000 plus 2,000 additional B2/C1 words. Do not claim Oxford 5000 complete until the full additional set is extracted and unresolved second-pass items reach zero.

## British audio

Technical generation remains 3,308 / 3,308 with aggregate structural integrity green. `Audio/pronunciation-overrides.tsv` contains 36 numbered/sense-marker candidates: 19 formatting-only `ready`, 17 heteronym/sense-sensitive `review`. Uppercase `CD`, `DVD`, `IT`, `OK`, `TV` remain explicit QA candidates. Runtime still does not depend on Kokoro/Python/API/network.

Targeted regeneration plumbing is implemented: `generate_british_audio.py` accepts the existing ledger's `entry_id`; `worddeck-audio.yml` validates the ledger before selecting only `status=ready` rows; the active request is exactly 19 files. This targeted batch is NOT yet marked verified here until its Actions result/artifact is inspected.

Reuse decision remains the existing Apache-2.0 Kokoro development-time pipeline and standard command-line/build tooling; no new audio/NLP/runtime subsystem was introduced.

## Exact next steps

1. Inspect the production attributed SentencePack run triggered by `6f79771cb023a7d37d6933e33ee741ff47afbf0e`; read `sentence-gap-summary.json` and record real exact-present/exact-absent counts for the 114 ordinary gaps.
2. Treat exact-present ordinary gaps as matcher/index QA, not morphology candidates. Evaluate a maintained development-time lemmatizer only for the exact-absent ordinary IDs if the measured set justifies it.
3. Preserve semantic distinction for sense-numbered/annotated records; only extend deterministic exact phrase/hyphen handling where measured evidence and existing production matching rules justify it.
4. Inspect the targeted 19-file pronunciation Actions result; if green, validate manifest IDs/audio_text and record the artifact checkpoint. Do not touch the 17 heteronyms until exact British pronunciation is established.
5. Resolve 17 audio heteronyms and 5 uppercase candidates before AudioPack completion.
6. Continue Oxford-5000 extraction/translation/second-pass QA in substantial verified batches; continue Oxford-3000 semantic QA without blocking usable Recall/Spelling/Sentence slices.
7. Never modify `main`.
