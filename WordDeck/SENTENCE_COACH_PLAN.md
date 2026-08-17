# WordDeck Sentence Coach plan

Status: approved design for implementation on `worddeck-bootstrap`.

## Goal

Add an offline sentence-training track that reuses the same dictionary entries and user-selected training decks while keeping its own progress/statistics. No cloud API, no Ollama/local LLM, no runtime Python/Java dependency.

The primary exercise is **Sentence Spelling**: WordDeck shows a Ukrainian sentence/prompt, the user types English, and the trainer checks the required English token multiset and exact spelling/forms. Base Sentence Spelling does not require canonical word order. A later strict Translation/Grammar mode may check syntax/order separately.

## Runtime architecture

The shipped WinForms application should contain only compact .NET logic and prebuilt sentence packs/indexes.

Components:

1. `SentencePack`: offline EN-UA sentence pairs with provenance/license, CEFR estimate, token/lemma index, target Oxford entry IDs, length/difficulty metadata.
2. `SentenceSelector`: searches/ranks candidate sentences for one or more target entry IDs.
3. `SentenceAnswerEvaluator`: tokenizes/normalizes the typed English response, compares required token multisets/forms, reports missing/extra/misspelled tokens, and does not require word order in Sentence Spelling mode.
4. `AdaptiveSentenceCoach`: deterministic local statistics/scheduling. Prioritize weak target words, reduce frequency of strong words, and keep decisions explainable/reversible.
5. Future `ControlledSentenceGenerator`: template/grammar based fallback for target-word combinations not covered by the corpus. It may use development-time NLG tools, but the release must not require their runtimes.

## Data-source strategy: corpus first, generator fallback

Fastest useful implementation is corpus-first. Build an offline EN-UA sentence pack from legally reusable parallel data (initial candidate: Tatoeba EN-UA pairs), then generate controlled sentences only for coverage gaps.

Do not bundle copyrighted learner books merely because they are CEFR-labelled. User-supplied/public-domain texts may be imported later through a separate source pipeline.

Development-time helper libraries may be downloaded and used if their licenses are compatible, but avoid adding Java/Python runtime requirements to WordDeck. Keep third-party notices/provenance.

## CEFR and personal difficulty

Oxford entry metadata supplies the level of target vocabulary. Sentence difficulty must be evaluated separately.

For every candidate sentence, precompute:
- English tokens and lemmas;
- CEFR level for known Oxford vocabulary;
- count/ratio of words above the target level;
- off-list/unknown lexical items;
- length and basic structural complexity;
- target Oxford entry IDs present in the sentence.

Do not depend only on a nominal A1/A2/B1/B2/C1 folder. Ranking should combine CEFR with the user's actual learned vocabulary. A higher-level word already mastered by the user should not automatically make a sentence undesirable; an unknown non-target word should be penalized strongly.

Default ranking principle for a target word of level L:
1. sentence contains the requested target lemma/form;
2. surrounding vocabulary is mostly <= L or already known by the user;
3. minimal unknown non-target vocabulary;
4. appropriate length/clarity;
5. good EN-UA pair quality;
6. avoid recently repeated sentences.

## One-word and multi-word targeting

The selector must support `targetEntryIds` with one or multiple words.

For two target words:
1. first search the indexed corpus for a sentence containing both lemmas;
2. if suitable candidates exist, rank by CEFR/personal-known-vocabulary difficulty;
3. otherwise fall back to controlled generation using both target words;
4. never silently substitute unrelated vocabulary as the training target.

This allows a custom deck of e.g. 200 unknown words to be trained with one, two, and eventually three target words per sentence.

## Answer semantics for Sentence Spelling

Example canonical English tokens:
`Oxford University improves the skills of students`

If the user enters the same required token multiset in a different order, Sentence Spelling may accept it as spelling-complete and explicitly state that word order is not checked in this mode.

Reject/diagnose:
- missing required token/forms;
- extra duplicated tokens when they replace required ones;
- misspellings;
- wrong required inflected form when strict-form checking applies.

Normalize only technical equivalences: case where appropriate, leading/trailing whitespace, repeated whitespace, standard/typographic apostrophes. Do not use edit-distance to mark a misspelling as correct.

`Show answer` remains a configurable shortcut and must still require the user to type the required spelling correctly before completion.

## Adaptive selection

Per target entry keep deterministic statistics such as first-try success, wrong attempts, hint/show-answer use, streak, recent outcomes and review timestamps. Sentence selection should increasingly emphasize words with poor recent spelling performance while periodically revisiting strong words.

If training from a user-selected 200-word deck, selection must remain constrained to that deck's target vocabulary unless the user changes scope. Non-target context words may appear only as sentence support and should be filtered/ranked by level and personal familiarity.

## Accessibility and shortcuts

All Sentence Coach commands must be keyboard reachable, NVDA/UIA friendly, conflict-checked, persisted, and rebindable through the existing shortcut settings system. Native WinForms text fields/controls only for the core interaction.

Likely actions:
- enter/leave Sentence Spelling;
- submit answer (Enter while answer field focused);
- show target spelling/answer;
- play British pronunciation for target word(s);
- next exercise only after successful completion;
- optional repeat Ukrainian prompt;
- enable/disable adaptive selection;
- Sentence Coach deck/scope controls.

## Implementation sequence

1. Stabilize basic Spelling track and independent spelling decks/statistics.
2. Define `SentencePack` schema + compact indexes.
3. Build development-time Tatoeba EN-UA import/filter/index pipeline and licensing attribution.
4. Add CEFR/personal-known-vocabulary scoring.
5. Implement one-target corpus selection.
6. Implement multi-target (2-word) corpus intersection search.
7. Implement token-multiset Sentence Spelling evaluator and NVDA workflow.
8. Add controlled generator fallback for corpus gaps.
9. Add deterministic adaptive sentence scheduling and regression tests.
10. Only later add strict grammar/translation mode if needed.

## Release gates

- no API/network requirement for training;
- no bundled secret/credential;
- no runtime Python/Java requirement;
- source/license provenance for every distributable sentence pack;
- deterministic tests for token evaluation, target-word indexing, CEFR ranking, two-target intersection, adaptive selection, persistence and accessibility command registry;
- do not call generated/template sentences `human translations` unless they actually are verified pairs.
