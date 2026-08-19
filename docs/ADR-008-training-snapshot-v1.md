# ADR-008: Training snapshot v1 and immutable exercise definitions

Status: accepted for the presentation-neutral local-training foundation.

## Context

`ExerciseSession.snapshot()` is an adapter-facing persistence boundary. Its
reader previously coerced every counter with `int(...)`, so booleans, decimal
text, and floats could become trusted session state. Missing fields silently
received defaults, unknown fields were ignored, and inconsistent combinations
such as an in-progress exercise with no attempts were partly representable.

The frozen exercise DTOs also accepted Python-only coercions and retained a
mutable metadata dictionary. A caller could therefore change supposedly stable
definition metadata after a session was created.

## Decision

1. New snapshots always write `schema_version: 1`.
2. A bounded legacy reader accepts the complete former unversioned snapshot
   shape. Explicit version values other than integer v1 fail closed.
3. Snapshot fields are exact: unknown and missing keys are rejected; counters
   must be non-boolean integers; status and exercise identity must be text.
4. Restored counters must describe a reachable state. Every submitted move is
   either one completed step or one mistake, so `attempts` must equal
   `step_index + mistakes`.
5. READY cannot contain move progress, IN_PROGRESS requires an attempt, and
   only COMPLETED may use the terminal step index.
6. Stable `TrainingErrorCode` values distinguish definition, command, schema,
   snapshot, identity, and unreachable-state failures.
7. Exercise definitions require exact tuple/frozenset/text/mapping boundaries.
   Metadata is copied into a read-only mapping and a session's definition
   reference cannot be reassigned through the public API.
8. Invalid move input is rejected before attempts, mistakes, status, or cursor
   state can change.

## Compatibility

Snapshots emitted before v1 remain readable when their full former shape is
present and valid. Valid definitions, normalized move text, hint behavior,
reset behavior, and deterministic progress semantics are unchanged. Payloads
that depended on Python scalar coercion, incomplete defaults, or mutable nested
metadata now fail explicitly.

No cross-language JSON Schema is claimed by this checkpoint. A future schema
must prove parity with the runtime's reachable-state equation and status/step
invariants before adapters may treat it as authoritative.

## Release boundary

This change provides reusable semantic DTO and persistence hardening only. It
does not activate Training UI, engine analysis, input bindings, assignments,
database migration, Stage-1 release integration, a QA workflow, or an NVDA
verification claim. Stage 2 remains blocked while the current candidate is
QA-owned.
