# ADR-021: Board query contract invariants

Status: accepted as a hardening addendum to the presentation-neutral board
service introduced before ADR-003.

## Context

The board command service is a read-only source for accessible presentation
adapters, but its frozen snapshots retained caller-owned attack dictionaries
and did not validate piece, move, engine, clock, square, or material DTOs.
Query operations also coerced arbitrary objects with `str()` or `int()`;
notably `rank(True)` and `rank("1")` were accepted as rank one.

## Decision

1. Canonical square parsing accepts only text or an exact non-Boolean integer
   in `0..63`. Text keeps the bounded trim/case normalization convenience.
2. `MoveView` requires distinct exact square indices, optional non-empty
   single-line SAN, and an exact Boolean capture flag.
3. `BoardSnapshot` requires an exact 64-entry tuple of canonical piece symbols,
   exact side-to-move, typed immutable legal moves, typed attack relations,
   optional typed last move, and optional canonical captured piece.
4. Attack mappings are validated, copied, and exposed read-only. Origins are
   exact unique square tuples and cannot include their target.
5. Engine, clock, square, and material DTOs validate exact text/scalar shapes.
   Material maps are detached and read-only, and point totals must equal the
   canonical piece-count calculation.
6. Service composition requires real snapshot DTOs and preserves falsey valid
   snapshot instances. Missing optional snapshots receive explicit empty DTOs.
7. Piece-cycle, rank, file, color, and direction inputs reject Python
   object-to-text, string-to-integer, and bool-as-integer coercion before query
   execution. Valid query ordering and wrap behavior remain unchanged.

## Compatibility

All 64 canonical text squares, exact integer square indices, board ordering,
legal-move/capture filtering, controller/attacker/defender semantics, material
calculation, piece cycling, engine/clock projections, and outer-whitespace or
case normalization for textual square/piece/file queries remain available.
Malformed snapshots and coercion-dependent calls now fail explicitly.

## Ownership boundary

The service owns an immutable board-query snapshot only. It does not own chess
legality, keyboard bindings, spoken strings, focus, UI state, engine processes,
clock progression, or position mutation. Adapters receive detached DTOs and
cannot mutate attack or material maps through exposed references.

## Release boundary

This change does not alter Web/Windows UI dispatch, keymaps, QA-owned workflows
or harnesses, packaging, the candidate ZIP, Stage 1 lineage, or NVDA claims.
Stage 2 remains blocked while the current candidate is QA-owned.
