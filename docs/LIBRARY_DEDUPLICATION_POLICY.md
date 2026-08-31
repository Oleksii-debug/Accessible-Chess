# Library deduplication policy

Status: D07 preservation-first contract.

Accessible Chess must recognise repeated chess content without destroying source provenance, comments, NAGs, variations or metadata. Duplicate evidence is therefore layered; no single digest is allowed to mean both “same source bytes” and “same chess content”.

## Identity layers

### 1. Source identity

Exact immutable source identity is:

`(normalized source_format, source_sha256)`

The source format is part of the key. The same bytes declared as PGN and CBH are not silently treated as the same source.

### 2. Source-record identity

One record within a source is:

`(normalized source_format, source_sha256, source_index)`

This key is provenance, not chess equality. A CBV container record and an extracted CBH record remain distinct source records even when both decode to the same canonical chess content. Container/extraction lineage may add provenance evidence later, but it must not replace the immutable source-record key.

### 3. Move identity

`GameMoveIdentity v1` hashes:

- starting position identity (`SetUp/FEN` when present);
- recursive move sequence;
- recursive variation move structure.

It deliberately ignores:

- comments;
- NAGs;
- result;
- PGN tags/metadata;
- source/provenance.

A terminal attached symbolic NAG such as `e4?!` is ignored only in this move-identity view, making it equivalent to `e4 $6` for duplicate classification. The canonical GameTree is not rewritten; full loss-preserving identities still distinguish the original forms.

### 4. Tree identity

Existing `GameIdentity v1.tree_digest` remains unchanged and includes starting position, recursive moves/variations, comments, NAGs and result.

### 5. Record identity

Existing `GameIdentity v1.record_digest` remains unchanged and adds normalized semantic PGN tags to the full tree identity.

## Deterministic classification

Strength order is:

1. `exact_source` — same PGN source format + exact byte SHA-256;
2. `record` — same full GameTree and same semantic tags;
3. `tree` — same full GameTree, tags differ;
4. `moves` — same starting position and recursive move graph, but annotations/result/metadata differ;
5. no match — distinct chess content.

For one stored game/incoming game pair only the strongest semantic classification is emitted.

## Preservation policy

Duplicate detection is read-only. It does not delete, overwrite, coalesce or enrich stored rows.

- Importing the same exact source is owned by `LibraryImportService`: source/game rows are reused only after canonical payload validation, while every import attempt remains durable provenance.
- Same moves from different sources are semantic siblings, not authorization to erase either source record.
- Different comments or NAGs are preserved as separate annotated records.
- Richer metadata is preserved as a separate record; no field is silently selected or overwritten by a “richer wins” heuristic.
- Same players/date with different move graphs are different games.
- CBH/PGN copies may share semantic identity while retaining distinct source records.
- CBV container provenance and extracted-CBH provenance remain distinct even if the decoded canonical game matches.

If a future UI offers a collapsed duplicate group or a user-approved merge, it must keep all source-record links and annotation variants and must be a separate explicit policy.

## Transaction and migration boundary

This child package adds no schema migration and changes no Library publication transaction. The active exact-repeat package remains authoritative for transaction-safe repeated-source reuse.

A persistent semantic-identity index is required for truly large-library O(log n)/indexed semantic lookup. That requires separately owned ACSDB schema/migration work. Until that ownership is available, duplicate classification reparses stored PGN rows but uses digest maps to avoid the previous stored-games × incoming-games comparison cross product.

## Accessibility and user-facing behavior

This layer is presentation-neutral. Search, open and export continue to expose the stored canonical records without hidden merge behavior. Any future duplicate-group UI must be keyboard/NVDA operable and must state when records differ in annotations, metadata or provenance.
