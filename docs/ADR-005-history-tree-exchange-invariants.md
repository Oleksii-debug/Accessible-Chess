# ADR-005: Versioned history-tree exchange invariants

Status: accepted for the presentation-neutral review core.

## Context

`ReviewHistory` is the single mutable owner of review cursor, branch identity,
and active-line selection. PGN, persistence, and presentation adapters exchange
`HistoryTreeSnapshot` values rather than maintaining a second mutable tree.

The v1 validator previously checked parent/child counts but did not prove that
every node was reachable from root. A disconnected component could form a
parent cycle, pass validation when the cursor stayed at root, and later make
lineage activation loop forever. Python booleans could also pass as schema
version, node IDs, child IDs, parent IDs, active-child IDs, or cursor IDs
because `bool` is an `int` subclass.

## Decision

1. Version 1 accepts exact integer identifiers only; booleans are never IDs or
   schema versions.
2. `nodes` and each `child_ids` collection must be tuples, matching the
   immutable exchange contract.
3. Node records must be contiguous and ordered from zero.
4. Root has no parent. Every non-root node has exactly one parent, and both
   directions of every parent/child link agree.
5. A traversal from root must reach every node exactly once. Disconnected
   cycles/components are rejected before any mutable `ReviewHistory` is
   created.
6. The exported cursor must exist and its complete parent lineage must be the
   selected active lineage.
7. `PositionSnapshot` requires non-empty text FEN, bounded side, typed
   optional text metadata, and a mapping context.
8. Context is copied on input/export and exposed through a read-only top-level
   mapping so caller dictionary mutation cannot alter stored history.
9. Invalid append data is validated before allocating or linking a node.
10. Navigation APIs reject boolean variation indexes rather than treating
    `True` as index 1.

Stable `HistoryErrorCode` values are:

- `invalid_command`;
- `out_of_range`;
- `unsupported_schema`;
- `invalid_snapshot`;
- `invalid_tree`.

## Compatibility

Snapshots produced by `ReviewHistory.export_tree()` already use exact
integers and tuples and remain schema version 1. Valid callers keep the same
node IDs and branch behavior. Inputs that depended on Python scalar/container
coercion or represented disconnected graphs now fail closed with a stable
error code.

## Release boundary

This change hardens the existing Stage-1-compatible review core and its neutral
exchange DTO. It does not add a post-Stage-1 user feature, database migration,
release merge, Windows QA change, or NVDA verification claim.
