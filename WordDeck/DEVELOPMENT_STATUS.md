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

`tools/analyze_sentence_gap_occurrence.py` measures only bounded exact evidence against the same attributed Tatoeba EN-UA pair input: exact single tokens, contiguous exact multiword sequences and conservative exact hyphenated forms. Sense-numbered/annotated records remain unmeasured.

Current checkpoint `029dcf7abedf7a23bba4a07ada0cb30f70839897` extends that analyzer with actionable QA classes without adding morphology:
- ordinary single-surface + exact corpus occurrence -> `exact_present_index_or_matching_defect_candidate`;
- ordinary single-surface + no exact occurrence -> `exact_absent_corpus_or_inflection_candidate`;
- safe exact phrase/hyphen present/absent -> bounded extension/corpus candidates;
- sense/semantic/unsafe structural cases remain `structural_or_semantic_review_required`.

The self-test now covers exact-present, exact-absent, phrase, hyphen and sense-protected classification paths. The attributed SentencePack workflow already runs this tool against freshly downloaded production pairs; real production class counts are still pending observation before any morphology dependency is introduced.

Reuse-first decision before morphology remains unchanged: do not invent a stemmer/lemmatizer. Maintained spaCy is suitable only as development-time evidence if exact-absent counts justify it; Catalyst is .NET-compatible but adds older model/runtime footprint. No morphology dependency is currently shipped or added.

## Oxford 5000

Embedded package remains 3,308 Oxford-3000 positions. Oxford-3000 semantic translation QA remains 240 reviewed / 208 verified / 32 needs-second-pass / 3,068 awaiting first pass.

Oxford-5000 additions extraction is incomplete. First 100 extracted B2/C1 additions have Ukrainian translations; ambiguous/polysemous/multi-POS records remain `needs_second_pass`. Do not claim Oxford 5000 complete until the full additional set is extracted and unresolved second-pass items reach zero.

## British audio

Technical generation remains 3,308 / 3,308 with aggregate structural integrity green. `Audio/pronunciation-overrides.tsv` contains 36 numbered/sense-marker candidates: 19 formatting-only `ready`, 17 heteronym/sense-sensitive `review`. Uppercase `CD`, `DVD`, `IT`, `OK`, `TV` remain explicit QA candidates. Runtime still does not depend on Kokoro/Python/API/network.

## Exact next steps

1. Observe/fix the attributed SentencePack workflow on the classified-gap checkpoint and record real present/absent counts for the 114 ordinary gaps.
2. Only for exact-absent ordinary gaps, evaluate a maintained development-time lemmatizer to measure inflected-form-only evidence; do not ship morphology unless runtime need is demonstrated.
3. Preserve semantic distinction for sense-numbered/annotated records; only add safe exact phrase/hyphen matching when corpus evidence justifies it.
4. Target-regenerate only the 19 safe pronunciation overrides; resolve 17 heteronyms and 5 uppercase candidates before AudioPack completion.
5. Continue Oxford-5000 extraction/translation/second-pass QA in substantial batches; continue Oxford-3000 semantic QA without blocking usable Recall/Spelling/Sentence slices.
6. Never modify `main`.
