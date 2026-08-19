# ADR-015: Analysis presentation contract invariants

Status: accepted for the semantic analysis presentation adapter.

## Context

The presentation adapter previously projected analysis through mutable
dictionaries and converted state, result, score, PV, FEN, index, and language
values with `bool(...)`, `int(...)`, and `str(...)`. Malformed downstream state
could therefore look valid to the WebView API. Stale and failed results could
also retain projected lines.

`enable()` stored its FEN before the continuous service accepted `start()`, and
`sync_position()` stored a new FEN before `update_position()` succeeded. A
service exception could leave adapter identity ahead of the actual analysis
session, weakening the stale-result guard used for screen-reader output.

## Decision

1. `AnalysisPresentationLine` is the immutable UI-neutral line DTO. It requires
   exact MultiPV, depth, `cp`/`mate` score, integer score value, and tuple PV
   fields, and serializes to the existing camel-case dictionary shape.
2. `AnalysisPresentation` validates enabled/running/FEN/limit/error/stale fields
   and an ordered line tuple. Disabled, stale, or failed presentations cannot
   carry active lines; enabled presentations require a FEN.
3. Presentation serialization remains detached. Mutating a returned PV list or
   line dictionary cannot mutate the underlying presentation DTO.
4. The adapter accepts `None` or a structurally compatible continuous-analysis
   service with callable start, update, stop, close, and state operations.
   Constructor limits reject scalar coercion while genuine integers retain the
   existing clamp policy.
5. Production `AnalysisLine` is the preferred input. Bounded compatibility is
   retained for an exact camel-case dictionary or a structural object with the
   five canonical snake-case fields; both are copied into the typed line DTO.
6. Structural state and result projections validate exact scalar/container
   shapes. A service-FEN mismatch, result-FEN mismatch, or upstream stale flag
   suppresses all lines. A current error also suppresses lines before their
   untrusted payload is inspected.
7. `enable()` and `sync_position()` publish adapter FEN and enabled state only
   after the corresponding service call succeeds. Failed calls leave the
   previous adapter identity unchanged.
8. PV index, displayed FEN, and language inputs fail explicitly. The supported
   speech languages remain `uk` and `en`; existing Ukrainian and English output
   strings and WebView dictionary keys are unchanged.

## Compatibility

WebView analysis fields, MultiPV ordering, enable/disable behavior, evaluation,
best-move and variation text, test-double composition, stale suppression, and
non-live status refresh remain unchanged for valid values. Error results now
fail closed without retaining lines. Inputs that depended on Python scalar
conversion or arbitrary `as_dict()` execution now fail explicitly.

## Ownership boundary

The adapter owns semantic projection and displayed-position suppression. It
does not own chess legality, the canonical board, continuous worker lifecycle,
Stockfish process composition, shortcut routing, DOM rendering, or screen
reader focus/live-region policy.

## Release boundary

This change does not redesign HTML, shortcuts, speech wording, WebView layout,
Stockfish behavior, Windows packaging, or QA-owned workflows. It does not merge
Stage 1, create a candidate ZIP, or claim NVDA verification. Stage 2 remains
blocked while the current candidate is QA-owned.
