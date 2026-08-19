# ADR-012: Engine-game session coordination invariants

Status: accepted for the presentation-neutral engine-game coordinator.

## Context

The engine-play DTO and provider boundary is strict, but the session coordinator
previously accepted arbitrary callback values, coerced board-owned values to
text, and exposed session snapshots without validating their nested state.
Starting a session assigned configuration and reset lifecycle state before the
clock factory and board-side provider had completed. A move was checked against
the clock only before asking the engine, so time could expire or the position
could change while the provider was computing a result.

The `None` best-move result also crossed an unvalidated no-move callback. That
made it possible for an incompatible adapter result to finish lifecycle state
through incidental errors instead of a stable engine contract.

## Decision

1. `INVALID_SESSION` is a stable `EngineContractErrorCode` for inconsistent
   composed session state. Existing request, result, config, handoff, and
   provider codes retain their meanings.
2. `EngineGameSessionSnapshot` requires canonical resolved-config, lifecycle,
   clock, side, and turn-state DTOs. Active turn ownership must match the
   configured engine side. Active timed sessions require a running or paused
   clock for the current side, untimed sessions require the canonical stopped
   zero clock, and finished sessions cannot retain an active clock.
3. Required board/history callbacks must be callable. Optional callbacks must
   be callable or `None`; injected lifecycle, clock factory, and service values
   must satisfy their explicit contracts. Falsey callable objects remain valid
   providers and are not replaced through truthiness fallback.
4. `start()` resolves configuration, constructs and starts a candidate clock,
   reads the canonical side, and validates the resulting session snapshot
   before resetting injected lifecycle state or publishing the new session.
   `reset()` likewise validates the side before lifecycle mutation.
5. Board-owned side, FEN, and history identity must be exact non-empty text in
   their declared shapes. The coordinator does not stringify, lowercase, or
   otherwise repair provider output.
6. An engine move is checked once before provider dispatch and again after the
   provider returns. The post-provider guard rejects an expired clock, changed
   side, or changed FEN before invoking the board commit callback.
7. `EngineNoMoveHandoff` carries validated FEN, side, and stable history
   identity. A resolver may return only `None` or `EngineNoMoveResolution`.
   Resolution is limited to a lifecycle-consistent checkmate or stalemate
   outcome; the coordinator never infers an outcome from `None` alone.
8. Position-outcome synchronization requires a started, active session before
   lifecycle mutation. Wrong handoff and resolver types fail before internal
   session state changes.

## Compatibility

Valid human/engine turn scheduling, level policy, untimed and timed games,
takeback clock restore, lifecycle intents, analysis/review handoffs, and
Stockfish composition are unchanged. Adapters that depended on coercion,
ignored invalid optional providers, stale engine results, or inconsistent
snapshot construction now fail explicitly.

## Ownership boundary

The coordinator does not own the canonical board, position legality, history
tree, or UI. The board commit callback remains responsible for applying one
validated move synchronously and atomically. Coordinator lifecycle and clock
state change only after that callback returns successfully; external callback
side effects cannot be rolled back by this layer.

The chess-state owner remains responsible for deciding whether a no-move
position is checkmate or stalemate. The engine provider remains responsible for
move search only.

## Release boundary

This change does not activate engine UI, change the Stockfish process or binary,
modify Windows packaging, alter QA-owned workflows, merge Stage 1, create a
candidate ZIP, or claim NVDA verification. Stage 2 remains blocked while the
current candidate is QA-owned.
