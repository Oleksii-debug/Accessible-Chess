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

## Release boundary

This ADR hardens an existing shared-core module and its file adapter. It does
not add a PGN UI, enable a post-Stage-1 phase, change the Windows release
composition, or modify any QA workflow/harness.
