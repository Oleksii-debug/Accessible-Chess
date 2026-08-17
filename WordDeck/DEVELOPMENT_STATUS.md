# WordDeck development checkpoint

Last updated: 2026-08-17
Branch: `worddeck-bootstrap` only. `main` is not a development target for this work.

## Regression baseline

Recall remains the compatibility gate: five permanent renameable core decks plus arbitrary user decks; stable IDs/shortcuts; no-repeat shuffle-bag navigation; accessible counts; custom pasted cards; autosave, backup and current-card recovery plus Ctrl+S; optional offline British pronunciation.

Spelling remains a separate persisted track with five core plus arbitrary user decks, native answer TextBox, exact spelling, wrong-answer lock, hints that still require correct typing, objective stats, conservative offline scheduling, automatic movement only among core spelling decks, reversible/explainable coach moves, and rebindable persisted commands. Do not claim NVDA verification until the user tests a Windows build with NVDA.

Current embedded Oxford package remains 3308 entries. Existing 3308-position British-audio generation is technically complete and must not be regenerated wholesale without a concrete defect.

## Sentence Coach — implemented and verified in code

The existing SentencePack schema/indexes, tokenizer, token-multiset evaluator, CEFR/personal ranking, recent-sentence penalty, selected-scope enforcement, SentencePackStore, Tatoeba import/provenance tooling and controlled-generator fallback contract remain reused rather than reimplemented.

Runtime Sentence Spelling now exposes a native WinForms path with:
- installed SentencePack selection and validated local import;
- spelling-deck scope selection;
- selectable one-target or two-target training;
- Ukrainian sentence prompt and native English answer TextBox;
- Enter submits locally; exact required token/forms are checked while word order is intentionally not assessed;
- concise missing/extra/misspelling feedback and no advance after an incorrect answer;
- Show Answer still requires subsequent correct typing;
- both one-target and two-target exercises keep every training target inside the selected spelling-deck scope;
- two-target mode uses the existing inverted indexes/intersection lookup and SentenceSelector ranking, and requires a real corpus sentence containing both selected target IDs;
- target weakness stats, recent sentences, active pack/deck, selected target count, current sentence and all current target IDs persist with primary+backup recovery;
- legacy one-target Sentence Coach state migrates to the new target-ID list;
- Show Answer, Repeat Prompt, SentencePack import and trainer entry commands remain in the existing rebindable shortcut system.

No new NLP/runtime dependency was added for two-target mode. This is WordDeck-specific UI/state glue over existing tested components.

## Real Tatoeba corpus checkpoint

Official weekly source pipelines were executed in GitHub Actions and validated against the current 3308-entry embedded Oxford package.

Provenance-safe CC0 path:
- English CC0 sentences: 41,502;
- Ukrainian CC0 sentences: 393;
- unique EN-UA links inspected: 217,546;
- pairs where both sides independently occur in official CC0 exports: 2;
- resulting pack covers only 11 unique current Oxford entry IDs.

Conclusion: the strict CC0 subset is legally clean but far too small to be the primary product corpus.

Attributed Tatoeba path (`CC BY 2.0 FR`):
- 207,578 accepted aligned EN-UA sentences in the generated SentencePack;
- 3,120 unique current Oxford entry IDs covered out of 3,308;
- 190,315 sentences contain at least two indexed target IDs;
- 160,058 contain at least three indexed target IDs;
- 53,612 carry conservative quality flags;
- zero accepted records missing per-side author attribution;
- every accepted record retains upstream English/Ukrainian sentence IDs and both Tatoeba usernames through the validated provenance path.

The attributed pack is a development artifact, not bundled into the application. Its raw JSON is large (about 246 MB), so distribution/loading must be made practical before treating it as a default shipped corpus. Reuse-first still applies: prefer built-in .NET compression/streaming or a small proven compatible component rather than inventing a new storage format.

Tatoeba text licensing/provenance decisions remain documented in `THIRD_PARTY_NOTICES.md`. Tatoeba audio is separate and is not implied by sentence-text reuse.

## Oxford 5000 content QA

Do not reset existing ledgers.

Oxford-3000 translation first-pass checkpoint remains:
- reviewed through `oxford-a1-0240`;
- 240 reviewed;
- 208 verified;
- 32 needs-second-pass;
- 3068 remaining first-pass positions.

Oxford-5000 additions extraction is still incomplete. The currently extracted first 100 B2/C1 additions now all have Ukrainian translations; unambiguous senses are marked `verified`, while polysemous/multi-POS/nuanced items remain explicitly `needs_second_pass`. Do not claim Oxford 5000 complete until the full additional set is extracted with stable POS/sense/CEFR distinctions and unresolved second-pass count is zero.

## Audio

Technical generation remains 3308/3308 current Oxford positions. Pronunciation QA plus coherent offline AudioPack manifest/integrity packaging remain outstanding. Generate audio for Oxford-5000 additions only after those entries are stable and verified.

## Exact next steps

1. Keep Windows CI/self-tests/published-EXE validation green; fix any regression before more feature work.
2. Harden the new two-target Sentence Spelling path only for demonstrated defects/performance issues; do not redesign green Sentence core components.
3. Make the attributed Tatoeba pack practical to distribute/load offline, using reuse-first evaluation of built-in .NET compression/streaming before adding dependencies; preserve attribution and provenance exactly.
4. Measure any remaining target-coverage gaps after practical corpus packaging; add morphology/lemma enrichment only if it materially closes those gaps, then deterministic controlled generation only for residual gaps.
5. Continue Oxford-5000 extraction/translation/second-pass QA in substantial batches.
6. Continue British AudioPack QA/integrity packaging without wholesale regeneration.
7. Commit only to `worddeck-bootstrap`; never modify `main`.
