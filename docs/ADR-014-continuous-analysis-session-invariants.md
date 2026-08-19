# ADR-014: Continuous-analysis session invariants

Status: accepted for the presentation-neutral continuous-analysis coordinator.

## Context

The continuous-analysis coordinator previously converted FEN, MultiPV, and
depth inputs with `str(...)` and `int(...)`. Its public state DTO did not enforce
the relationship between the running flag and active FEN, and constructor
dependencies were accepted without validating the service or callback shape.

There was also a shutdown race: a result callback runs on the analysis worker.
If that callback called `close()`, the coordinator attempted to join its current
thread. The resulting exception was swallowed by the callback guard after the
closed flag changed but before the underlying analysis service was closed.

## Decision

1. `ContinuousAnalysisState` validates exact running, FEN, MultiPV, depth,
   revision, and `AnalysisResult` fields. A running state requires a non-empty
   FEN; MultiPV remains 1–10, depth 1–40, and revision is non-negative.
2. The coordinator requires a real `AnalysisService`. An optional result sink
   must be callable or `None` before any worker or state is created.
3. `start()`, `update_position()`, and `configure()` reject boolean, float,
   numeric-text, bytes, and container coercion with
   `EngineContractError(INVALID_REQUEST)`. Genuine integer values retain the
   existing clamp policy.
4. FEN whitespace is normalized once at the coordinator boundary. The stored
   state, pending request, invalidation token, provider call, and published
   result therefore use the same canonical text.
5. Request validation and provider invalidation happen before publishing new
   continuous-session state. A new worker is placed in its waiting state before
   the first pending request becomes visible.
6. A callback may stop or close the service from the worker thread. `close()`
   never joins the current thread, but still closes the underlying
   `AnalysisService`; the worker observes the closed flag on its next loop.
7. Result callbacks remain isolated from the worker: callback exceptions do not
   terminate subsequent analysis. Only results matching the active revision and
   FEN are published.

## Compatibility

Valid start/update/configure flows, integer clamping, request coalescing, stale
suppression, callback isolation, stop/restart, idempotent close, and provider
ownership remain unchanged. Stored FEN now uses normalized text. Inputs that
relied on Python scalar conversion now fail before state mutation.

## Ownership boundary

The coordinator owns request coalescing, revision identity, worker lifecycle,
and the downstream `AnalysisService` lifetime. It does not own chess legality,
Stockfish process composition, UI projection, speech, or the canonical board.

The UI adapter remains responsible for comparing the displayed position with a
published result. This decision does not broaden UI input or output contracts.

## Release boundary

This change does not activate or redesign analysis UI, alter Stockfish search
commands or binaries, modify Windows packaging, touch QA-owned workflows, merge
Stage 1, create a candidate ZIP, or claim NVDA verification. Stage 2 remains
blocked while the current candidate is QA-owned.
