# WordDeck Stage 18 — morphology data contract

## Current production boundary

This branch does **not** bundle a production Word Families/morphology corpus. No approved real relation dataset with verified redistribution terms is present in the current live project state.

The implementation therefore provides production ingestion, validation, diagnostics, query, Context integration and practice tooling while keeping the external-data boundary explicit. Synthetic examples exist only in deterministic tests and must never be packaged or described as production lexical-family data.

## Required source metadata

Every accepted overlay package must provide:

- `packageId` and schema version;
- source ID and source name;
- explicit license information;
- attribution text;
- optional source URI/version;
- per-relation evidence reference.

If package-level provenance/license/attribution is missing, the whole overlay fails closed. If an individual relation is malformed or uncertain, that row is quarantined and valid independent rows may continue for analysis. A release candidate is stricter: any quarantined issue blocks release eligibility.

## Stable-ID rule

Morphology is an overlay over canonical lexical IDs. It never merges dictionary entries and never owns Recall, Spelling, Sentence, Grammar, Listening or Reading progress.

Relations are imported by exact stable IDs, not by surface-word matching. Physical lexical forms may be ambiguous (`record` noun vs `record` verb, etc.). Equal spelling is never sufficient evidence that two canonical entries are the same item or belong to the same family.

## TSV format

Metadata uses comment lines:

```text
# schemaVersion=1
# packageId=<stable package id>
# sourceId=<source id>
# sourceName=<human-readable source>
# license=<license identifier/text>
# attribution=<required attribution>
# sourceUri=<optional absolute URI>
# version=<optional source version>
```

The exact header is:

```text
relationId\tfamilyId\tfromEntryId\ttoEntryId\tkind\tmorpheme\tevidenceRef
```

Supported explicit relation kinds are `Derivation`, `Prefix`, `Suffix`, `Root`, and `Compound`. Prefix, suffix and root relations require an explicit morpheme/root value. Unknown relation kinds are not guessed.

## Coverage and gap accounting

`MorphologyDiagnostics` measures coverage on the exact dictionary stable-ID universe, not on unique written forms. It reports accepted relations, families, per-kind counts, per-CEFR coverage, exact stable-ID gaps and touched equal-written-form ambiguity groups.

The ambiguity report is informational: an explicitly source-backed relation may legitimately reference one stable ID whose written form is shared by another entry. The sibling homograph remains a separate gap until it has its own source-backed relation evidence.

Machine release evidence is intentionally separate from the relation package. A source SHA-256, dataset class, explicit redistribution approval and approval reference are required before the machine gate can call a candidate structurally release-eligible. Even then, the result is not an independent legal/source audit PASS.

## Sentence / Context integration

`MorphologyContextTargetPlanner` is a fail-closed physical-form boundary before related stable IDs reach downstream corpus selection. By default, an ambiguous homograph cannot be used as a Context anchor and ambiguous related targets are excluded even when the morphology relation itself is exact and valid.

A downstream identity owner may supply an explicit `resolvedAmbiguousEntryIds` set only after separate POS/sense evidence proves those exact stable IDs. Morphology never generates or infers that proof. Resolution is per stable ID: proving `record` verb does not resolve a sibling `record` noun. The physical form remains recorded as ambiguous even when one exact ID has been cleared for downstream use.

`MorphologyContextBridge` calls the canonical Stage-11 product facade after this guard. One-target anchor selection and natural two/three-target discovery therefore reuse the existing Sentence/Context ranking, study-pool and learner-vocabulary logic rather than duplicating it inside Stage 18.

## Grammar / Reading reuse seams

`MorphologyGrammarBridge` requires an explicit Grammar skill reference and resolves it through the canonical `GrammarSkillReferenceResolver`. Morphology never infers a Grammar skill from a suffix, prefix, POS guess or written form. It contributes only exact source-backed lexical targets after the same ambiguity guard.

`MorphologyOverlay` and `MorphologyPracticeService` expose stable-ID projections for Grammar and Reading. These contain related canonical IDs, lexical forms, CEFR levels, family IDs and explicit relation kinds. Downstream modes can request related targets without duplicating morphology inference or modifying canonical progress. The same physical-form ambiguity guard can be applied before any downstream mode interprets a written token as one lexical identity.

The practice service is deterministic and stateless: it produces explanation/exercise contracts and checks supplied answers, but does not mutate personal profile state. A future cross-mode adaptive lane can persist morphology evidence through the shared learner model without changing lexical identity.

## Release gate for real morphology data

A future production relation pack is releasable only after an independent check confirms:

1. source provenance is real, reproducible and bound to the exact source hash;
2. redistribution/license terms permit the intended bundle;
3. required attribution is included in release notices;
4. every referenced Oxford/user stable ID resolves exactly;
5. no source-form heuristic silently merges ambiguous entries;
6. invalid/uncertain records are quarantined rather than inferred, and the final release candidate has zero unresolved quarantines;
7. stable-ID coverage/gap accounting is published for the exact candidate;
8. scale/lookup tests remain bounded at the 5,446-entry Oxford baseline and beyond;
9. exact Windows production build, published-app regression tests and Stage-18 deterministic tests are green.
