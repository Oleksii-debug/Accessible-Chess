# ADR-001: Registration-based chess engine providers

Status: Accepted

## Context

Accessible Chess must support replacing Stockfish or adding another engine without changing chess rules, presentation code, or engine-consuming application services. Engine ports already isolate subprocess details, but there was no stable composition-root registration point for selecting among multiple implementations.

## Decision

Core exposes a presentation-neutral `EngineProviderRegistry` keyed by stable lowercase provider IDs. Infrastructure registers lazy factories plus capability metadata. Consumers select a provider by ID and may require analysis or move-generation capability before an adapter is created.

The registry depends only on `acs.engine_ports`; it does not import Stockfish, subprocess, WebView2, filesystem layout, SQLite, or packaging code. Registration does not instantiate engines.

## Consequences

A future UCI or non-UCI adapter can be added by implementing `ChessEnginePort` and registering a factory at the composition root. Existing engine consumers and UI contracts do not need provider-specific branches. Provider IDs are configuration/API identity and should remain stable once persisted or exposed.
