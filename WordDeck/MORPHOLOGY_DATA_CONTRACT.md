# WordDeck Stage 18 — morphology data contract

## Current production boundary

This branch does **not** bundle a production Word Families/morphology corpus. No approved real relation dataset with verified redistribution terms was available in the current canonical project state when this lane started.

The implementation therefore provides production ingestion, validation, query and practice tooling while keeping the external-data boundary explicit. Synthetic examples exist only in `MorphologySelfTest.cs` and must never be packaged or described as production lexical-family data.

## Required source metadata

Every accepted overlay package must provide:

- `packageId` and schema version;
- source ID and source name;
- explicit license information;
- attribution text;
- optional source URI/version;
- per-relation evidence reference.

If package-level provenance/license/attribution is missing, the whole overlay fails closed. If an individual relation is malformed or uncertain, that row is quarantined and valid independent rows may continue.

## Stable-ID rule

Morphology is an overlay over canonical lexical IDs. It never merges dictionary entries and never owns Recall, Spelling, Sentence, Grammar, Listening or Reading progress.

Relations are imported by exact stable IDs, not by surface-word matching. This is deliberate: physical lexical forms may be ambiguous (`record` noun vs `record` verb, etc.). Equal spelling is never sufficient evidence that two canonical entries are the same item or belong to the same family.

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
relationId	familyId	fromEntryId	toEntryId	kind	morpheme	evidenceRef
```

Supported explicit relation kinds are `Derivation`, `Prefix`, `Suffix`, `Root`, and `Compound`. Prefix, suffix and root relations require an explicit morpheme/root value. Unknown relation kinds are not guessed.

## Reuse seams

`MorphologyOverlay` exposes stable-ID projections intended for Sentence, Grammar and Reading lanes. These projections contain related canonical IDs, lexical forms, CEFR levels, family IDs and relation kinds. Downstream modes can request related targets without duplicating morphology inference or modifying canonical progress.

The practice service is deterministic and stateless: it produces an exercise contract and checks the supplied answer, but does not mutate personal profile state. A future cross-mode adaptive lane can persist morphology evidence through the shared learner model without changing lexical identity.

## Release gate for real morphology data

A future production relation pack is releasable only after an independent check confirms:

1. source provenance is real and reproducible;
2. redistribution/license terms permit the intended bundle;
3. required attribution is included in release notices;
4. every referenced Oxford/user stable ID resolves exactly;
5. no source-form heuristic silently merges ambiguous entries;
6. invalid/uncertain records are quarantined rather than inferred;
7. scale/lookup tests remain bounded at the 5,446-entry Oxford baseline and beyond.
