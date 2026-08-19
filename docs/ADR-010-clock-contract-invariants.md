# ADR-010: Clock scalar, snapshot, and monotonic-time invariants

Status: accepted for the presentation-neutral local-game foundation.

## Context

Clock controls and snapshots previously relied on Python comparisons and
`int(...)` conversion. Booleans and floats could become milliseconds, raw text
could masquerade as `ClockState` because the enum derives from `str`, and a
truthy non-boolean `resume_running` value could restart a restored clock.

Fast snapshot polling also reset the monotonic baseline even when less than one
millisecond had elapsed. Repeated sub-millisecond reads could therefore discard
time indefinitely. Non-finite or backwards values from an injected time source
were not reported through a stable clock error contract.

## Decision

1. `TimeControl` fields are exact non-boolean, non-negative integers. The
   untimed sentinel is exactly zero initial time with zero increment.
2. `ClockSnapshot` validates exact millisecond scalars, exact `ClockState`, side
   values, and all active/state/flagged cross-field invariants at construction.
3. `restore()` revalidates even a forged snapshot before mutation and accepts
   only a real boolean for `resume_running`.
4. Untimed restore accepts only the canonical stopped zero snapshot; it does
   not silently normalize a running or paused DTO.
5. Administrative remaining-time updates require exact integer milliseconds.
6. A live or paused clock cannot be reassigned through `start()`; callers must
   use the explicit move switch, resume, reset, or restore operation.
7. Sub-millisecond elapsed time remains in the monotonic baseline until a full
   millisecond can be charged.
8. Injected time values must be finite numeric non-booleans and never move
   backwards. Invalid time-source reads fail before state-changing restore,
   start, resume, or switch assignments.
9. Stable `ClockErrorCode` values distinguish control, command, state, snapshot,
   and time-source failures.

## Compatibility

Valid timed and untimed controls, pause/resume, move increments, flagging,
stop/reset, and historical restore behavior are unchanged. `ClockError` remains
a `ValueError`. Payloads that depended on scalar coercion, raw enum text,
noncanonical untimed state, live-clock reassignment, or invalid monotonic time
now fail explicitly.

## Ownership boundary

The clock owns elapsed-time accounting only. It does not decide legal moves,
whose turn a canonical position represents, mating capability after timeout,
game results, persistence, or UI timer cadence. `ClockSnapshot` remains an
in-memory DTO; this checkpoint does not claim a cross-language wire schema.

## Release boundary

This change does not activate a clock UI, engine behavior, online protocol,
Stage-1 merge, QA workflow, candidate ZIP, or NVDA verification claim. Stage 2
remains blocked while the current candidate is QA-owned.
