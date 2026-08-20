# ADR-004: Loss-aware PGN and GameTree serialization boundary

Status: accepted for the presentation-neutral core foundation.

## Context

`acs.gametree` is the neutral structural boundary used by PGN file services,
semantic identity, ACSDB import, and future replaceable adapters. It preserves
comments, NAGs, recursive variations, tags, and source warnings without making
the parser a second chess-legality engine.

The previous serializer had three silent-loss paths:

- semicolon comments were rewritten as brace comments, so a literal `}` could
  terminate the serialized comment and corrupt later tokens;
- a header/movetext `Result` mismatch was reported while parsing but the next
  save silently replaced the original header value;
- duplicate tag names were collapsed by the dictionary model without an
  explicit warning.

These behaviors violated the canonical requirement that malformed or unusual
PGN must never be silently reinterpreted as clean data.

## Decision

1. Comment syntax is a bounded `CommentStyle`: `brace` or `semicolon`.
2. Parsed semicolon comments serialize as semicolon comments, including literal
   braces, parentheses, NAG-like text, Unicode, quotes, and backslashes.
3. Comment placement before a line, after a move number, and after a move is
   kept in distinct GameTree slots across serialization.
4. A comment that cannot be represented in its declared PGN syntax fails
   closed with `GameTreeSerializationError`; it is never rewritten into a
   different semantic comment.
5. Stable error codes are:
   - `invalid_comment_text`;
   - `unsupported_comment_style`;
   - `unrepresentable_comment`.
6. A valid movetext result remains the canonical game result. A conflicting
   header `Result` stays in the tag record and remains accompanied by a
   warning after save/reload.
7. An invalid header `Result` is preserved as source evidence but cannot
   become the canonical domain result; the domain falls back to `*`.
8. Duplicate tag names retain the existing last-value behavior but now produce
   an explicit warning naming the collapsed tag.
9. Empty game collections serialize to empty text. Multiple games use a blank
   separator.
10. The multi-game splitter tracks multiline brace-comment state. A line that
    looks like a PGN tag while inside `{...}` remains comment text and cannot
    create a phantom game.
11. Comments after a root or nested result marker remain ordered trailing
    comments and round-trip in their original syntax.
12. A result marker terminates its current RAV. If a damaged nested RAV contains
    more move, annotation, or variation tokens before its closing parenthesis,
    the parser consumes that bounded tail inside the damaged child and emits an
    explicit depth-qualified quarantine warning. Those tokens can never leak
    into the parent mainline or become sibling variations.
13. Every quarantined nested-RAV tail creates a structured
    `PgnRecoveryIssue(post_result_rav_tail)` with depth, token count, message and
    export policy. `serialize_game(s)` and atomic PGN save fail closed with
    `unresolved_recovery` until a caller explicitly repairs the GameTree and
    removes the issue. Read-only importer inspection classifies that game as
    `DAMAGED`; ACSDB import rolls back atomically and records a failed attempt.
14. The same fail-closed policy covers every parser path that discards or
    structurally repairs source data. Stable recovery codes now cover duplicate
    tags, unterminated brace comments/RAVs, unmatched closing RAVs, orphan RAVs
    and annotations, replaced/dangling move numbers, root post-result tails and
    unknown tokens. Each becomes `DAMAGED` and blocks clean export. Invalid or
    conflicting `Result` headers remain exportable warnings because both the
    original header evidence and effective movetext result are preserved.
15. Symbolic NAG suffixes attached to SAN and numeric NAGs attached without
    whitespace are tokenized as annotations, never retained inside `MoveNode.san`.
    Mixed forms preserve source order, so `e4!?$1` becomes SAN `e4` with NAGs
    `!?`, `$1`. Malformed dollar forms or unsupported symbolic runs create an
    `invalid_annotation` recovery blocker. Mutable DTOs containing `!`, `?` or
    `$` inside SAN fail serializer validation instead of reintroducing the old
    ambiguity.
16. Move-number indicators accept only the canonical `n.` and `n...` forms.
    Other dot runs, including `n..`, create an `invalid_move_number` recovery
    blocker while the following SAN remains inspectable. Numeric NAGs accept
    only canonical `$0` through `$255`; leading-zero, out-of-range, oversized,
    or alphanumeric forms retain their exact token in an `invalid_annotation`
    issue and block export. Serializer validation applies the same grammar to
    mutable GameTree DTOs.
17. Tag-pair decoding accepts only PGN's `\"` and `\\` escapes as clean.
    A syntactically tag-shaped line with any other escape keeps the intended
    tag value for inspection, preserves the unsupported spelling in an
    `invalid_tag_escape` issue, and blocks export. Other lines beginning with
    `[` outside a brace comment create a `malformed_tag` blocker rather than
    becoming SAN. A damaged header starts or remains with exactly one bounded
    game, so clean sibling records retain independent quality.
18. Direct parsing and serialization use explicit collection-wide resource
    envelopes before unbounded growth: 64 Mi characters, two million lines,
    one million tokens/serialized fields/tags, 100,000 games/tree nodes, 512
    tag pairs per game, depth 128, and bounded tag/comment/token/recovery
    fields. File open rejects sources above 64 MiB before capture, uses bounded
    chunks plus a second full fingerprint, and file save rejects UTF-8 output
    above 64 MiB before creating a parent directory, lock, or temporary file.
    Stable failures distinguish input characters, lines, tokens, games, tags,
    fields, tree depth/nodes, output characters, source bytes and output bytes.
    ACSDB and duplicate provenance hashing now encode UTF-8 incrementally.
19. Chess legality is a separate non-destructive projection in
    `acs.gametree_legality`. It starts from the standard position or an exact
    `SetUp "1"` plus structurally and semantically valid `FEN`; inconsistent
    setup tags fail closed. Each move is resolved against an immutable parent
    position, and every RAV starts from the position before its owning move.
    Immutable links expose stable structural paths, source/canonical SAN, UCI,
    before/after FEN and `legal`, `legal_noncanonical`, `illegal` or
    `unverified` status. Path-qualified diagnostics distinguish illegal SAN,
    noncanonical spelling/check suffix, move-number mismatch, unavailable
    ancestry and forced checkmate/stalemate result mismatch. Castling,
    promotion, en passant and check/checkmate use the same chesscore rules.
    Parser recovery codes remain a distinct report field and the source
    GameTree is never mutated.
20. Read-only file inspection combines structural and legality evidence per
    game without contaminating clean siblings. Blocking recovery, invalid
    starts, illegal/unverified moves and forced-result errors are `DAMAGED`;
    legal noncanonical SAN and move-number diagnostics are `WARNING`; exact
    legal games are `FULL`. ACSDB validates structure first (preserving stable
    recovery failures), then legality before opening its source/game write
    transaction. Any damaged game rejects the whole collection, leaves no
    source/game rows and records a failed attempt with stable legality code,
    source index and bounded path evidence. Warning-only games retain original
    SAN and persist diagnostic summaries in `warnings_json`. Direct
    `store_game` uses the same gate and cannot bypass legality validation.
21. A caller-supplied `raw_pgn` is evidence, not an unchecked storage escape.
    It must parse to exactly one structurally exportable and legally linkable
    game whose versioned record identity equals the already validated
    `PgnGame`. Empty, multi-game, damaged, illegal, or different raw text is
    rejected before SQL insertion with stable validation codes. Warning
    evidence from both equivalent representations is retained without
    rewriting the supplied bytes.

## Compatibility

Valid brace-comment PGN remains valid and keeps its existing representation.
Semicolon comments become more faithful: their syntax is no longer normalized
to braces. Header/movetext mismatches remain visibly mismatched instead of being
silently repaired. Callers that construct impossible comments now receive a
stable, actionable error rather than corrupted output.

Post-result tokens inside a malformed nested RAV are excluded from the
canonical recovered GameTree and reported as quarantined. The untouched source
file remains the raw evidence. The recovered tree can be inspected but cannot
be exported or imported into ACSDB until explicit repair clears its structured
blocker, so the damaged tail is never silently normalized away.

Game identity schema v1 does not change: `CommentStyle` values serialize to the
same `brace` and `semicolon` strings already used by the identity payload.
Recovery evidence is source/provenance policy, not canonical chess content, and
therefore remains outside the semantic tree/record hashes.

Mixed multi-game inspection is per-game: a damaged record does not cause a
clean sibling to be mislabeled. Persistence remains atomic: writing a
collection containing any unresolved recovery issue produces no partial PGN,
source row, or game row.

Canonical move numbers and numeric NAGs now have one parser/serializer domain.
Valid boundary values `$0` and `$255` round-trip; spellings such as `$01`,
`$256`, `$1bad`, `1..` and `1....` remain visible as damaged source evidence
and cannot be normalized into a clean database record.

Valid tag values containing quotes and backslashes retain their decoded value
through parse/serialize cycles. Unsupported escapes and malformed tag lines
remain in structured source diagnostics and cannot become clean movetext,
phantom moves, or silently normalized headers.

Normal multi-game files remain in-memory and round-trip unchanged within this
envelope. Larger collections must use a future streaming importer; they are
never partially parsed or partially written by the current API. Oversized
source rejection leaves the source untouched, and oversized export rejection
creates no destination directory, save lock, or temporary file.

Legality linking can inspect a recovered tree without erasing recovery
evidence. An illegal mainline move makes later mainline positions unverified,
but a sibling RAV attached to that move remains independently verifiable from
the known pre-move position. A legal but noncanonical spelling can advance the
position while remaining explicitly diagnosable; no source SAN is rewritten.

Importer quality is therefore evidence-backed rather than syntax-only. This
changes no ACSDB schema: existing v2 rows remain readable, while new writes
gain stricter validation and richer warning JSON. Legality-damaged input is
never partially stored even when a clean game precedes it in the same source.

The optional raw-text path now has the same trust boundary as ordinary import.
Whitespace and header ordering can remain byte-for-byte source evidence, but
the bytes cannot describe a second game or a different semantic record than
the indexed tags and GameTree. This changes no identity schema or ACSDB schema.

## Release boundary

This ADR hardens an existing shared-core module and its file adapter. It does
not add a PGN UI, enable a post-Stage-1 phase, change the Windows release
composition, or modify any QA workflow/harness.
