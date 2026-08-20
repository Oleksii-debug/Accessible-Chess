# ADR-023: Duplicate and GameIdentity evidence invariants

Status: accepted as a hardening addendum to the versioned GameTree identity and
read-only duplicate-detection services.

## Context

`identity_for_game()` traversed a mutable `PgnGame` once for `tree_digest` and a
second time inside `record_digest`. Concurrent or aliased mutation could produce
two digests describing different tree states in one identity DTO. Cyclic
variation objects failed through Python recursion rather than a bounded domain
error.

Duplicate matches and reports had no runtime invariants. Stored `pgn_text` was
coerced with `str()`, so binary or malformed database content could be silently
interpreted or skipped without evidence that semantic comparison was incomplete.

## Decision

1. Game identity accepts only `PgnGame` and snapshots tags plus every recursive
   line/move/comment collection once. The exact same tree payload feeds both the
   tree and record digests.
2. Tags, lines, moves, comments, SAN, NAGs, results, and container kinds are
   validated at the identity boundary. Raw or mutated DTO shapes fail with a
   stable `GameIdentityContractError` code.
3. Recursive traversal detects active-object cycles and enforces explicit depth
   and node limits before JSON hashing. Shared acyclic subtrees remain
   representable.
4. `GameIdentity` requires the current exact schema version and lowercase
   SHA-256 digests.
5. Duplicate matches enforce kind-specific fields: exact-source evidence carries
   only source identity, while record/tree evidence carries positive stored IDs,
   non-negative incoming index, current identity version, and digest.
6. Duplicate reports validate immutable match/skipped-ID tuples and exact-source
   digest consistency. `has_incomplete_evidence` exposes whether stored games
   were skipped.
7. Duplicate detection accepts only `AcsDatabase` and text. Stored non-text,
   unparsable, multi-game, or invalid-identity rows are isolated and their game
   IDs are reported instead of being coerced or silently ignored.
8. Every incoming parsed game must be structurally exportable and legally
   linkable before exact-source or semantic matches are returned. One damaged
   game rejects the entire incoming collection with a stable structural,
   legality, or identity code, source index, and bounded unique evidence-code
   tuple; partial duplicate evidence is never exposed.
9. Each legacy stored row must also be structurally exportable and legally
   linkable before its record/tree identity is compared. Invalid legacy rows
   remain untouched and appear in `skipped_stored_game_ids`; they cannot produce
   a semantic duplicate claim. Exact-source SHA-256 evidence remains a distinct
   source-level claim and its hashing algorithm is unchanged.

## Compatibility

Identity schema version 1, whitespace/header-order stability, recursive
variation/comment/NAG sensitivity, exact-source SHA evidence, record-before-tree
match strength, incoming source indexes, deterministic stored-game order, and
read-only ACSDB behavior remain unchanged for valid data.

Legal warning-only inputs remain comparable without normalization. An illegal
incoming collection now fails closed instead of returning even an otherwise
valid exact-source match. A valid incoming source may still report exact byte
identity while explicitly skipping a corrupted legacy game row, because those
are separate evidence domains.

## Ownership boundary

Identity hashing owns a bounded immutable payload snapshot, not the mutable
GameTree. Duplicate detection reads ACSDB and reports evidence only; it never
deletes, coalesces, repairs, or rewrites a stored or incoming record.

## Release boundary

This change does not alter ACSDB schema/migrations or stored rows, import or UI
flows, QA-owned workflows or harnesses, packaging, candidate ZIP, Stage 1
lineage, or NVDA claims. Stage 2 remains blocked while the current candidate is
QA-owned.
