# ADR-007 — PGN workspace collection services

Status: accepted on `feature/core-forward-foundation`.

Base before this subsystem sprint: `77adecfa9acdf21713f10eaf35f08898d76c9c3d`.

## Decision

`acs.gametree` remains the sole structural source of truth for PGN games, moves, comments, NAGs and recursive variations. `acs.pgn_workspace` is an application-level collection service over those same `PgnGame` objects. It may index, search, fingerprint, report, navigate, append/remove and deterministically export games, but it must not copy the move tree into a second mutable model.

Stable neutral references continue to come from `acs.game_references`: `VariationRef`, `MoveRef` and `PositionRef`. Exact RAV branch/return semantics are resolved against the canonical `PgnGame` tree. Database, book and presentation adapters may persist or exchange these refs and fingerprints without learning internal parser details.

The workspace owns no chess legality. SAN/FEN legality, side-to-move and board mutation remain the responsibility of chess Core when the PGN subsystem is integrated with the Stage 1 game engine. The PGN workspace therefore preserves notation and SetUp/FEN source data and reports semantic diagnostics, but never invents legal positions or repairs moves by guessing.

## Practical scope

The workspace provides collection-scale import/export, typed per-game import reports, aggregate statistics, deterministic SHA-256 content fingerprints, duplicate grouping, metadata/mainline search, selection export, stable source identity allocation for appended games, direct neutral-reference resolution and a deterministic structural navigation stream with variation-enter/variation-exit markers.

Large-corpus tests exercise 1,000 games with recursive variations in addition to the existing GameTree corpus. This is deliberately an in-memory application service, not a replacement for ACSDB. Storage adapters remain free to index the neutral outputs while the SQLite repository remains owned by its existing data layer.

## Failure and recovery policy

Malformed records stay present when the canonical parser can recover them. `PgnSemanticRecord.usable` and typed diagnostics decide whether a downstream operation may treat a record as semantically usable. Search/export do not silently delete malformed games. Duplicate grouping is content-based and independent of `source_index`; source identity remains a collection navigation identity, not database identity.

## Consequences

A UI or database adapter can now consume a practically useful PGN collection subsystem without reparsing strings, duplicating RAV traversal, inventing branch-return rules or owning another game tree. Proprietary ChessBase binary decoding is explicitly outside this ADR.
