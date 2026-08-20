# ADR-026: bounded classic CBG token framing without chess semantics

Status: accepted for the replaceable, read-only ChessBase evidence boundary.

## Context

The classic ChessBase stack already proves family integrity, CBH record spans,
CBP/CBT metadata, CBG headers/custom setup prefixes, and exact opaque move
payload bytes. Calling those bytes decoded moves would be false: the repository
has no licensed real-file corpus broad enough to prove the proprietary move
mapping, and the pinned reference's chess projection depends on GPL
`python-chess`, which is intentionally excluded.

The pinned MIT reference does provide a smaller independently useful fact: the
payload has a counter-obfuscated token stream with exact one-byte/two-byte and
variation-control boundaries. That boundary can be proven without constructing
a position or importing a game.

## Decision

1. `acs.chessbase_cbg_tokens` consumes only an exact
   `ClassicCbgMovePayloadEvidence`. It revalidates the DTO's exact scalar types,
   fixed standard/custom payload start, end span, immutable bytes, and SHA-256
   before processing any token.
2. The framing algorithm is adapted from `asdfjkl/cbh2pgn` pinned at
   `42b3592738062db1f768239e85df1b98cb1cead9`, copyright 2022 Dominik Klein,
   MIT License. The exact 256-byte two-byte substitution table is local to this
   neutral module. No `python-chess` or other GPL runtime code is imported.
3. Every frame preserves payload/source offsets, raw encoded bytes,
   de-obfuscated code or 16-bit candidate word, counter before/after, and
   variation depth before/after. One-byte and two-byte values remain
   candidates; they are never labelled with a piece, square, SAN, FEN, or legal
   move.
4. Counter behavior follows the pinned implementation exactly. The four
   control codes do not increment it. A two-byte frame increments once after
   its two operands. The `0xAA` null candidate does increment because it is not
   in the pinned special-code set, regardless of the contradictory nearby
   upstream comment.
5. A successful framing must consume the exact payload through one final
   terminator with balanced variation controls. Truncated two-byte frames,
   unmatched ends, open variations, missing termination, invalid evidence, and
   invalid limits fail closed with stable domain codes and no partial result.
6. At most 100,000 token frames and 128 nested variation controls are accepted.
   Callers may lower but not raise those hard bounds.
7. `framing_complete=True` means only that this byte/control boundary is
   complete. `decoder_available` and `safe_to_import` remain false. No
   `GameTree`, PGN, ACSDB record, or full/lossless compatibility claim may be
   created from framing evidence alone.

## Evidence

Synthetic tests cover mixed one-byte/control/null/filler/two-byte streams,
counter wrap, every substitution-table index at every possible counter value,
balanced and malformed variation controls, truncation, termination, hard
resource limits, evidence tampering, exact source offsets, and the continued
absence of chess/import semantics. The architecture gate keeps the module
presentation-neutral, storage-neutral, and free of `python-chess`.

## Release boundary

This is additive read-only shared-core evidence. It changes no Stage 1 product
source, QA workflow, release lineage, package, database schema, or NVDA status.
Canonical ChessBase move decoding remains unsupported until independent
real-fixture, legality, variation, annotation, and round-trip evidence exists.
