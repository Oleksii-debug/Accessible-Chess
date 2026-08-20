# ADR-006: BookDocument v1 semantic serialization contract

Status: accepted historical foundation; v2 legality and product behavior are
superseded by ADR-029.

## Context

`BookDocument` is the neutral semantic boundary between source adapters and
accessible readers/indexes. It must not depend on DOCX, HTML, PGN file layout,
ChessBase records, SQLite, or a particular UI.

The original dictionary round-trip had no schema version and accepted several
Python coercions that other languages would not reproduce. For example,
`Heading(level=True)` passed because `bool` converts to integer 1, and a
string level could pass construction but later break `BookIndex` arithmetic.
Direct block lists could contain unsupported objects, and `extend()` could
partially mutate a document before encountering a bad later item.

## Decision

1. `BookDocument.as_dict()` always emits `schema_version: 1`.
2. `from_dict()` accepts exact version 1 plus the unversioned pre-v1 shape as
   a bounded legacy read. The next serialization always writes version 1.
3. Boolean, string, and float values never stand in for integer heading levels
   or game IDs.
4. Block kinds and fields are closed sets. Unknown kinds/fields fail with a
   stable code rather than disappearing.
5. Block/source identifiers are non-empty text and are normalized only by
   trimming boundary whitespace.
6. Position, Diagram, VariationTree, and Exercise FEN values are checked as
   structural 4- or 6-field records: eight exact ranks, canonical empty runs,
   bounded pieces/turn/castling/en-passant, and canonical counters.
7. All required and optional text values have exact text semantics. A supplied
   blank optional field is invalid rather than silently equivalent to missing.
8. Direct document construction validates block and warning collections and
   detaches the caller-owned lists.
9. `append()` validates before mutation. `extend()` materializes and
   validates the complete input before changing reading order.

Stable `BookDocumentErrorCode` values are:

- `invalid_field`;
- `unknown_field`;
- `unsupported_schema`;
- `unsupported_block_kind`.

## Compatibility

The semantic block names and field names are unchanged. Existing valid
unversioned dictionaries remain readable and migrate on the next write. Valid
documents gain only the top-level schema marker. Inputs that relied on Python
coercion, noncanonical FEN text, unsupported objects, or partial bulk mutation
now fail closed.

No JSON Schema is published by this ADR. Publishing a cross-language schema
requires proving exact parity for the structural FEN rules rather than
advertising a weaker pattern as equivalent.

## Release boundary

This is a reusable semantic-contract hardening change. It does not activate a
books UI, training phase, database migration, Stage-1 release merge, QA
workflow, or NVDA verification claim.
