# ADR-025: GameTree copy-on-write editing and cursor remapping

Status: accepted for the presentation-neutral PGN/GameTree core.

## Context

Canonical navigation made every RAV address and return location explicit, but
the completion line still lacked safe promote, reorder, and delete operations.
Direct list mutation would let a stale index edit another sibling, partially
modify the caller's tree on failure, lose comments/results during promotion,
and strand database/book/engine cursors on a different structural node.

## Decision

1. `acs.gametree_editing` is the sole structural edit boundary. It consumes the
   canonical `PgnGame` and immutable navigation paths; it creates no parallel
   chess or accessibility tree.
2. `VariationEditTarget` binds the exact parent path/move/variation indexes to
   the current GameIdentity v1 record digest. Any intervening semantic change,
   including sibling insertion/reorder, rejects the request as
   `stale_revision` before copying or mutation.
3. Every operation validates exact scalar/container types, the full bounded
   graph, move and line reuse, depth, node count, and target existence before
   deep-copying the source. All edits occur only on the detached copy.
4. Reorder moves exactly one sibling line while preserving every object field.
   Delete removes exactly one selected subtree. Promote replaces the parent
   continuation with the selected line, makes the old continuation variation
   zero, keeps remaining siblings in order, then keeps alternatives formerly
   attached to the promoted first move.
5. Promotion transfers variation-leading comments to the promoted first move,
   retains selected trailing comments/result on the new continuation, preserves
   the old continuation's trailing comments/result on its demoted line, and
   updates an existing root `Result` tag when the promoted line has an explicit
   result. Tags, SAN, NAGs, before/after comments, source index, warnings, and
   recovery issues are otherwise preserved.
6. Every valid source line cursor, including end-of-line, has one immutable
   `CursorRemapEntry`. Reordered/promoted contexts resolve to their exact new
   structural path; deleted subtree contexts map to `None`; unknown source
   cursors fail explicitly instead of guessing.
7. The remap itself is bounded by the same line-plus-move node envelope and is
   deterministic for identical requests. Edited clean games serialize/reparse
   to the same versioned record identity, while the original serializes exactly
   as before.

## Compatibility

No PGN wire, GameIdentity, legality, ACSDB, or HistoryTree schema changes. The
new API is additive. Direct mutable-list callers remain possible at the DTO
level, but product/database/book/engine adapters must use this service when
they need atomic editing and context restoration.

## Release boundary

This is reusable shared-core work only. It activates no Stage 2 UI, release
lineage, QA workflow, candidate package, or NVDA verification claim.
