# ADR-002: Core-forward PGN semantic diagnostics boundary

Status: accepted for isolated future work.

## Base and isolation

`feature/core-forward-foundation` was created from exact previously green Data/GameTree head:

`a56073a1b71247d984412844bbd0bc72e4e2924e`

This branch is intentionally separate from `feature/teaching-classroom-foundation` and from the frozen Stage 1 release/Core handoff. Nothing on this branch is part of a Windows candidate unless Integration later consumes an exact green handoff.

## Context

`acs.gametree` is the existing authoritative recursive PGN structure model. It preserves tags, comments, NAGs, RAVs, result tokens and parser warnings. Replacing or copying that model beside Core would create a second source of truth.

Downstream import/storage/UI code nevertheless needs stable machine-readable semantics for SetUp/FEN/result validation and malformed-record reporting. Parsing human warning strings independently in each adapter would create inconsistent policy.

## Decision

Keep `acs.gametree` authoritative for PGN structure. Add `acs.pgn_semantics` as a read-only projection over `PgnGame` that provides:

- immutable tag projection that preserves extension tags;
- explicit `PgnSetup(enabled, fen)` values;
- stable typed diagnostic codes and severities;
- source index and field attribution for diagnostics;
- fail-closed errors for invalid Result, invalid SetUp, and SetUp=1 without FEN;
- warning-only preservation of FEN without SetUp=1 instead of silently inferring intent;
- preservation of all existing parser warnings as typed diagnostics.

This layer does not parse SAN, validate FEN chess legality, mutate GameTree, decode ChessBase files, or own persistence.

## Consequences

Adapters can consume deterministic diagnostics without scraping prose. Existing PGN loss-preserving behavior and recursive branch identity remain unchanged. Chess legality and FEN position validity continue to belong to the canonical chess/Core services rather than this data-contract layer.
