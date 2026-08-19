# ADR-017: UCI adapter request and parser invariants

Status: accepted for the serialized UCI engine adapter.

## Context

The UCI adapter previously converted path, FEN, depth, MultiPV, skill, and move
time inputs with `str(...)` and `int(...)`. A newline in FEN or a direct command
could inject an additional UCI command. Malformed `info` lines without depth or
score were converted into fabricated depth-zero centipawn evaluations.

Parser completion used `startswith("bestmove")`, so unrelated tokens could end
a search. Invalid best-move text and the standard `0000` no-move token were not
distinguished. A process factory could return an incompatible object, and a
startup/handshake failure left process and reader state attached to the adapter.

## Decision

1. Adapter path and process factory are exact constructor contracts. Path must
   be non-empty single-line text; the factory must be callable.
2. FEN and direct UCI commands must be non-empty single-line text. Boolean,
   float, numeric-text, bytes, container, CR, and LF coercion is rejected before
   a process or command-stream mutation.
3. Genuine integer MultiPV, depth, and skill values retain their existing clamp
   policies. Move time retains the existing 50-millisecond minimum without a
   new maximum.
4. Public engine operations share a reentrant serialization lock. Starting a
   replacement process joins the prior reader briefly and drains stale output
   before the new handshake.
5. A process factory result must expose the process, stdin, stdout, wait, poll,
   and terminate operations required by the adapter. Incompatible output fails
   with `EngineContractError(INVALID_PROVIDER)` before publication.
6. Handshake failure terminates/waits the candidate, clears process and reader
   identity, drains queued output, and leaves the adapter open for a later
   retry. Handshake tokens must match a full response line.
7. An analysis `info` line is published only when MultiPV, depth, score kind,
   score value, and a non-empty standard UCI PV are all present and valid.
   Missing, out-of-range, malformed, or non-UCI lines are ignored rather than
   repaired with invented values.
8. Search completion requires the exact `bestmove` token. Standard coordinate
   moves, optional promotion, `(none)`, and `0000` are supported. Missing or
   malformed best-move tokens fail with `INVALID_RESULT` in both analysis and
   move-search paths.

## Compatibility

Serialized analysis/play access, request-local UCI option restoration, integer
clamping, MultiPV ordering, promotion moves, `(none)`, timeouts, idempotent
close, and the existing command sequence remain unchanged for valid data.
`0000` now correctly maps to no move. Inputs and engine output that depended on
coercion, prefix matching, or fabricated parser defaults now fail closed.

## Ownership boundary

The adapter owns one UCI process, its reader, serialized command stream, request
options, and syntactic UCI parsing. It does not validate that a FEN is a legal
chess position or that a syntactically valid PV/best move is legal in that
position. Those facts remain with the chess-state owner and engine protocol.

## Release boundary

All verification for this decision uses scripted in-memory process/queue test
doubles. The change does not launch, add, replace, download, or package a real
engine binary; redesign UI; touch QA-owned workflows; merge Stage 1; create a
candidate ZIP; or claim NVDA verification. Stage 2 remains blocked while the
current candidate is QA-owned.
