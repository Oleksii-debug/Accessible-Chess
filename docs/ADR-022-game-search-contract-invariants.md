# ADR-022: Game search query and page invariants

Status: accepted as a hardening addendum to the presentation-neutral ACSDB
search service.

## Context

`GameSearchQuery.normalized()` converted limits and cursors with `int()`, so
Boolean, float, and numeric-string values could silently change paging. Search
also used truthiness to select the default query and did not require an actual
query DTO.

Although SQL values were parameterized, user `%` and `_` characters still kept
their `LIKE` wildcard meaning. A search intended as literal text could therefore
match unrelated rows. Returned item/page DTOs had annotations but no runtime
shape or cursor-consistency validation.

## Decision

1. Text filters accept only text or `None`, collapse whitespace, and map blank
   text to no filter. Result, source ID, cursor, and limit use exact scalar
   types; bool-as-int and string/float conversion are rejected.
2. The service accepts only a real `AcsDatabase` and `GameSearchQuery` or
   `None`. Falsey foreign objects can no longer become an unrestricted default
   query.
3. Every text filter is bound as a SQL parameter and `%`, `_`, and the escape
   marker are escaped before `LIKE ... ESCAPE '!'`. Player/event/opening/source
   searches remain literal contains matches; ECO remains a literal prefix.
4. Search items validate positive database identities, non-negative source
   index, canonical import/result values, mandatory source text, and exact
   optional text fields. Trusted rows are no longer silently converted with
   `str()` or `int()`.
5. Search pages require an immutable tuple of typed items with strictly
   increasing game IDs. A non-final page exposes exactly its final visible ID
   as the next cursor; a final page exposes no cursor.

## Compatibility

Case-insensitive search, combined filters, keyset paging, the 1..200 page-size
bound, normalized filter whitespace, deterministic ID order, source provenance,
and parameterized SQL remain unchanged. Literal `%`, `_`, and `!` now search for
those characters instead of expanding the match set.

## Ownership boundary

The service performs read-only database queries and returns validated neutral
DTOs. It does not expose SQL, mutate ACSDB, own UI state, or implement
accessibility presentation. Callers own query values and immutable returned
pages.

## Release boundary

This change does not alter the database schema or migrations, import data,
Web/Windows UI, QA-owned workflows or harnesses, packaging, candidate ZIP,
Stage 1 lineage, or NVDA claims. Stage 2 remains blocked while the current
candidate is QA-owned.
