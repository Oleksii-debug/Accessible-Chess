# ADR-024: Canonical GameTree navigation invariants

Status: accepted for the presentation-neutral PGN/GameTree core.

## Context

The loss-aware parser preserves recursive RAV lines, but the completion line
had no canonical structural cursor. Older Stage 2 branches contained a useful
prototype, `gametree_navigation.py`, whose paths and enter/leave behavior were
not hardened against Python scalar coercion, malformed mutable containers,
cycles, shared line objects, excessive depth, or node counts. Reimplementing a
cursor in each database, book, engine, and accessible presentation adapter
would create competing tree semantics and unreliable return locations.

## Decision

1. `PgnGame` remains the only GameTree. Navigation exposes immutable
   `VariationStep`, `MoveAddress`, `BranchReturnContext`, and `GameTreeCursor`
   values over the same mutable-owner tree; it creates no flattened NVDA tree.
2. A path step identifies the parent move index and that move's variation
   index. Paths and cursor indexes require exact non-negative integers;
   booleans, floats, strings, and mutable path containers are rejected.
3. The cursor is the next move to consume. A cursor equal to the current line
   length is a valid end-of-line state; larger indexes fail explicitly.
4. A branch can be entered only from the cursor immediately after its owning
   move. Leaving any nested branch returns to that same parent path at exactly
   `owner index + 1`, including a legal parent end cursor.
5. Resolution never falls back to a nearby line, move, or first variation.
   Invalid paths and transitions expose stable error codes.
6. Deterministic pre-order traversal yields each move address exactly once and
   enforces the parser's shared depth/node envelopes. Active-line cycles and
   acyclic line-object reuse have distinct failures.
7. Navigation is read-only. Parsing, serialization, annotations, source SAN,
   warnings, and recovery evidence remain byte/identity neutral after any
   sequence of navigation calls.
8. The canonical `VariationStep` type is shared by legality diagnostics and
   navigation so path evidence cannot diverge between those services.

## Salvage decision

The prototype from `integration/data-forward-vertical-20260816` is classified
`REBASE_AND_ADAPT`: its structural addressing and resume semantics were kept;
its unchecked recursion, loose scalar contracts, and untyped failures were
replaced by the current bounded invariants.

## Compatibility

Valid prototype callers retain root path `()`, zero-based move/variation
indexes, pre-order traversal, and enter/leave behavior. Unsafe inputs now fail
closed instead of relying on Python coercion or recursion errors. No PGN wire
format, identity schema, or ACSDB schema changes.

## Release boundary

This is reusable shared-core work only. It adds no Stage 2 UI, release merge,
QA workflow change, candidate package, or NVDA verification claim.
