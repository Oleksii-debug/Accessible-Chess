# ADR-007: Book navigation snapshot isolation

Status: accepted for the presentation-neutral reader/index foundation.

## Context

`BookIndex` describes itself as immutable and `BookReader` stores stable
semantic locations and return points. Both previously retained the caller's
live mutable `BookDocument`. Clearing, reordering, or replacing that external
block list after construction could make index entries disagree with their
source blocks, invalidate return points, or raise unrelated index errors.

Navigation inputs also inherited Python coercion: `True` could select block 1
because booleans are integers, while string filter kinds silently returned an
empty result instead of reporting a contract mismatch.

## Decision

1. Index and reader construction require a validated `BookDocument`.
2. Each component takes an internal semantic snapshot through the versioned
   `BookDocument.as_dict()/from_dict()` contract.
3. Navigation and indexing operate on a private tuple of snapshot blocks.
4. The public `document` property returns a new detached copy. Mutating that
   copy cannot change entries, cursor, heading paths, or return points.
5. BookTarget requires non-empty text key, exact non-negative integer index,
   and typed optional semantic identifiers.
6. Contents depth, reader indexes, target values, entry kinds, search text, and
   search kind sets reject booleans and other scalar/container coercion.
7. Return-point names are exact non-empty text normalized at the boundary, so
   saving `" analysis "` and restoring `"analysis"` address one point.
8. Invalid navigation input never changes the current reader location.

## Compatibility

Valid documents, entry keys, reading order, heading paths, and return-point
behavior are unchanged. The isolation is a defensive copy at component
construction, not a new data owner or source of chess truth. Inputs that
depended on live external mutation or Python coercion now fail explicitly.

## Release boundary

This is reusable semantic navigation hardening only. It does not activate a
Books UI, mouse/keyboard binding, training phase, database migration, Stage-1
release merge, QA workflow, or NVDA verification claim.
