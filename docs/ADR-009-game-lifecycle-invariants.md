# ADR-009: Game-lifecycle outcome and handshake invariants

Status: accepted for the presentation-neutral local-game foundation.

## Context

`GameOutcome` previously checked only the result/winner pairing. It could still
represent checkmate by a draw, stalemate by a win, or a draw agreement with a
winner. Because `EndReason` derives from `str`, raw text such as `"checkmate"`
could also pass set membership and become stored as if it were the enum.

Timeout mating capability accepted arbitrary truthy values, and a later draw
offer or takeback request could overwrite the actor who owned an already
pending handshake. The immutable public snapshot DTO had no validation for
active-with-outcome, finished-without-outcome, or finished-with-pending states.

## Decision

1. Outcomes require exact `EndReason` values and stable
   `LifecycleErrorCode.INVALID_OUTCOME` failures.
2. Draw agreement, stalemate, insufficient material, threefold repetition, and
   the fifty-move rule require `1/2-1/2` with no winner.
3. Resignation and checkmate require a decisive result and matching winner.
4. Timeout explicitly permits either a decisive result or a draw because the
   opponent's mating capability is supplied by the canonical chess-state owner.
5. `opponent_can_mate` must be a real boolean; invalid input is rejected before
   any lifecycle state changes.
6. Draw and takeback handshakes retain their original actor until accepted,
   declined, expired by a committed move, or reset. A second request cannot
   silently replace pending ownership.
7. Public `LifecycleSnapshot` values validate status, outcome, pending actors,
   and cross-field state consistency on construction.
8. Stable error codes distinguish invalid commands/outcomes/states, missing
   interactions, self-responses, and already-pending interactions.

## Compatibility

Valid draw, resignation, timeout, position-derived result, takeback, reset, and
move-commit flows are unchanged. `LifecycleError` remains a `ValueError`.
Callers that relied on raw reason strings, truthy non-booleans, impossible
outcome matrices, or overwriting a live handshake now fail explicitly and
atomically.

## Ownership boundary

The lifecycle service does not determine checkmate, stalemate, repetition,
material, legal moves, or clock facts. It validates the semantic outcome
reported by the canonical position/clock owner and coordinates only lifecycle
state. `LifecycleSnapshot` remains an in-memory DTO; this checkpoint does not
claim a persistence or cross-language wire schema.

## Release boundary

This change does not activate a game UI, engine provider, online protocol,
input binding, Stage-1 merge, QA workflow, candidate ZIP, or NVDA verification
claim. Stage 2 remains blocked while the current candidate is QA-owned.
