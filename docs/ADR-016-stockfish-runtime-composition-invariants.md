# ADR-016: Stockfish runtime composition invariants

Status: accepted for the packaged Stockfish composition boundary.

## Context

`StockfishRuntimeConfig` previously accepted arbitrary values and used
`str(...)` truthiness to decide whether an explicit path existed. Blank text,
booleans, numbers, bytes, or objects could therefore reach `Path(...)` or be
silently treated as fallback configuration. A falsey callable engine builder
was replaced by the default UCI builder.

The runtime checked a builder result only through an incidental protocol test.
If provider close failed, the runtime discarded its only provider reference and
marked itself permanently closed, so composition code could not retry cleanup.

## Decision

1. `StockfishRuntimeConfig` accepts only non-blank `str`, `Path`, or `None` for
   configured path and application directory. Supplying neither remains valid
   configuration, but resolution then raises the existing typed not-found error.
2. `resolve_stockfish_path()` requires the canonical config DTO. An explicit
   configured path remains authoritative; otherwise the stable packaged
   relative path is resolved from the application directory. Both path sources
   expand a leading user-home marker.
3. Filesystem resolution errors, including invalid path syntax and symlink
   resolution failures, become `StockfishInvalidExecutableError`. Existing
   not-found, non-file, and empty/corrupt distinctions remain intact.
4. Runtime construction requires the canonical config DTO and a callable
   builder or `None`. A falsey callable builder remains the configured builder
   and is never replaced through truthiness fallback.
5. A built provider must be a non-class `ChessEnginePort` with callable
   analysis, best-move, and close operations. Incompatible output raises the
   stable `StockfishProviderError` before publication.
6. Failed construction or incompatible provider output leaves the runtime open
   and uninitialized, so a later provider request can retry the builder. Valid
   provider identity remains singleton for the runtime lifetime.
7. Runtime close still prevents any provider reopening. If the owned provider's
   close operation fails, the provider reference is retained only for a later
   cleanup retry. A successful retry clears it, and subsequent close calls are
   idempotent.

## Compatibility

Explicit-path authority, packaged-path identity, lazy construction, one shared
provider for analysis and engine play, runtime-only ownership, and close-once
behavior remain unchanged for valid configurations. Blank or non-path values,
falsey-builder replacement, class providers, and unretryable failed cleanup are
no longer accepted.

## Ownership boundary

The runtime owns path resolution, one packaged provider instance, and provider
shutdown. Analysis and engine-play services receive `runtime.provider` with
`owns_engine=False`. They do not close the shared subprocess; composition code
must close dependent services before closing the runtime.

This boundary does not validate chess moves, PV legality, UCI option semantics,
or the authenticity/version of a non-empty executable file.

## Release boundary

This change does not add, replace, download, execute, or package a Stockfish
binary; alter UCI search commands; redesign UI; touch QA-owned workflows; merge
Stage 1; create a candidate ZIP; or claim NVDA verification. Stage 2 remains
blocked while the current candidate is QA-owned.
