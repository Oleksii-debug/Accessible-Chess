# ADR-0001: Registration-based external import adapters

Status: Accepted

## Context

Accessible Chess must add PGN, ChessBase-family and future database/document formats without making the WebView2 UI, chess domain model or ACSDB persistence depend on proprietary file layouts. Issue #7 requires evolution by extension rather than repeated application rewrites.

## Decision

External source formats are routed through a presentation-neutral `ImportRegistry` and `ReadOnlyImporter` contract. An importer declares the suffixes it owns and returns neutral `ImportReport` data. UI and ACSDB code must not dispatch directly on proprietary binary structures.

Registration collisions fail explicitly. Replacing an adapter requires an explicit `replace=True` operation so an experimental decoder cannot silently take ownership of a format. Unknown suffixes fail explicitly rather than being dropped. Source files are immutable inputs; verified decoders may only create neutral output such as GameTree/ACSDB/PGN.

Recognition is not decoding. ChessBase component probing may describe `.cbh`, `.cbg`, `.cbv` and related files without claiming import compatibility. A decoder is registered only when its behavior is verified by tests/samples.

## Consequences

Adding a new source format normally means implementing one adapter plus tests and registering it at the composition root. Existing chess rules, WebView2 screens and database internals do not need to be rewritten. Importer routing can be contract-tested independently. Future plugin loading can reuse the same registry without changing the domain model.
