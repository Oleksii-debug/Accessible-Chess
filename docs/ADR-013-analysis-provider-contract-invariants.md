# ADR-013: Analysis DTO and provider contract invariants

Status: accepted for the presentation-neutral engine-analysis service.

## Context

The analysis service previously converted request limits and provider output
with `int(...)` and `str(...)`. Booleans, floats, numeric text, arbitrary score
kinds, mutable PV containers, or malformed legacy tuples could therefore cross
the engine boundary as apparently valid analysis. Factory and ownership inputs
were also accepted through truthiness, and an incompatible provider failed only
through incidental attribute errors.

Provider sequences were retained after releasing the serialized engine lock.
A provider that reused or mutated a result list could consequently change what
the service normalized for a completed request.

## Decision

1. `RawAnalysisLine` is the canonical provider DTO. Depth and score are exact
   non-boolean integers, depth is non-negative, score kind is `cp` or `mate`,
   and PV is an immutable tuple of non-empty move text.
2. `AnalysisLine` requires a 1–10 MultiPV index and reuses the canonical raw-line
   invariants. `AnalysisResult` requires exact FEN, generation, stale flag, and
   `AnalysisLine` tuple shapes. Stale or failed results cannot carry lines.
3. `as_dict()` remains the presentation serialization boundary and returns
   detached lists; mutating a serialized payload cannot mutate the DTO.
4. Public FEN, MultiPV, depth, factory, and ownership inputs no longer use
   scalar or truthiness coercion. Valid integer MultiPV and depth values retain
   the existing clamp policy of 1–10 and 1–40.
5. A provider must satisfy `AnalysisEnginePort`, including callable `analyze`
   and `close` methods. Its result must be a non-text sequence with no more
   lines than requested.
6. New providers return `RawAnalysisLine`. Existing providers retain a bounded
   legacy read path for exactly `(depth, (score_kind, score_value), pv_moves)`;
   legacy PV list/tuple input is copied into the canonical immutable tuple.
7. Provider output is copied and validated while the stateful provider lock is
   held. Staleness is checked after that snapshot, so mutable provider aliases
   cannot alter the published result.
8. Invalid public requests raise `EngineContractError(INVALID_REQUEST)` before
   generation or provider state changes. Provider construction, execution, and
   result failures retain the compatible `AnalysisResult.error` surface; an
   exception with no message receives a non-empty class-name fallback.

## Compatibility

Valid legacy tuples, canonical raw lines, integer limit clamping, generation
invalidation, serialized provider access, stale suppression, owned/unowned
shutdown, and the existing dictionary field names remain unchanged. Values
that depended on Python scalar conversion, malformed tuple unpacking, extra
provider lines, or mutable result aliases now fail explicitly.

## Ownership boundary

The service coordinates one analysis provider and snapshots provider output. It
does not own chess legality, validate that PV moves are legal in the supplied
FEN, interpret centipawn values for presentation, or manage the Stockfish
binary/process when `owns_engine=False`.

Continuous-analysis and UI-presentation adapters remain downstream consumers;
their own request/state coercion boundaries are not widened by this decision.

## Release boundary

This change does not activate or redesign analysis UI, alter Stockfish search
commands or binaries, modify Windows packaging, touch QA-owned workflows, merge
Stage 1, create a candidate ZIP, or claim NVDA verification. Stage 2 remains
blocked while the current candidate is QA-owned.
