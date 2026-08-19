# ADR-011: Engine-play configuration, handoff, and move DTO invariants

Status: accepted for the presentation-neutral engine-play foundation.

## Context

Engine configuration and move DTOs previously used `int(...)`, `str(...)`, and
`bool(...)` at trust boundaries. Booleans, floats, numeric text, or arbitrary
objects could become levels, move times, FEN text, ownership flags, history
identifiers, or handoff intents. Intent-irrelevant fields were accepted and
silently ignored.

The move service also trusted factory and provider outputs until attribute use.
An incompatible provider or a non-text best-move value therefore escaped the
contract through incidental Python errors or an invalid result DTO.

## Decision

1. Stable `EngineContractErrorCode` values distinguish request, result, config,
   handoff, and provider failures.
2. `EngineMoveRequest` requires non-empty FEN text, an exact non-boolean integer
   level, and optional exact integer move time. FEN whitespace is normalized.
3. `EngineMoveResult` requires `None` or non-empty move text, level 1–10, and an
   integer effective move time of at least 50 milliseconds.
4. `EngineGameConfig`, `EngineLevel`, and `ResolvedEngineGameConfig` validate
   their exact scalar and nested DTO types. Start configuration remains strict
   to levels 1–10.
5. `level_policy()` preserves the existing clamp for genuine integer values
   outside 1–10, but rejects boolean, float, text, and container coercion.
6. Side mode accepts only `EngineSideMode` or text aliases. A random chooser
   must be callable and return exact `"w"` or `"b"` text.
7. Lifecycle handoffs require only actor; analysis handoffs require only FEN;
   final-review handoffs require only stable history identity. Irrelevant data
   fails instead of being silently dropped.
8. The service requires a real `EngineMoveRequest`, callable factory, boolean
   ownership flag, structurally compatible move provider, and validated move
   output before exposing an `EngineMoveResult`.
9. Integer custom move times remain bounded to the existing 50-millisecond
   minimum; the change removes coercion rather than removing that policy.

## Compatibility

Valid level policies, white/black/random selection, lifecycle dispatch,
analysis/review handoffs, provider reuse, idempotent close, no-legal-move
`None`, and Stockfish composition remain unchanged. Invalid values that relied
on Python coercion, ignored handoff fields, or incidental provider errors now
fail explicitly.

## Ownership boundary

The engine-play service chooses policy and coordinates adapters. It does not
validate FEN legality, decide legal moves, own Position/GameTree, implement UCI,
or infer game outcome from `None`. Provider/process ownership remains behind
`MoveEnginePort` and the production Stockfish composition boundary.

## Release boundary

This change does not activate engine UI, change a Stockfish binary/process,
modify Windows packaging, merge Stage 1, alter QA workflows, create a candidate
ZIP, or claim NVDA verification. Stage 2 remains blocked while the current
candidate is QA-owned.
