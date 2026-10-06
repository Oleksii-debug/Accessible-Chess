# Book to Library record identity

The canonical semantic Game block may carry `game_record_digest` with a referenced
`game_id`. This is the existing versioned `identity_for_game(...).record_digest`,
not an independently computed book hash. It accounts for canonical game structure,
comments, annotations and record metadata.

`AcsdbBookGameLookup.make_book_reference` creates such a bound authoring block using
the existing read-only ACSDB lookup. The normal Book game resolver loads and detaches
the canonical GameTree, then verifies its record digest before returning it to the
Book Board or Training consumers. Missing records fail through the existing lookup
boundary. A mismatched record fails with `reference_changed`; no search, substitution
or reinterpretation is attempted.

Legacy ID-only blocks remain database-local for compatibility. They are not portable
record identities. Their wire payload does not gain a null digest field, preserving
existing reader revisions and progress snapshots. Newly created bound references
require the same canonical record; a changed annotation or metadata requires explicit
authoring rebinding. This does not migrate the database or modify its games.

Qualification covers same numeric ID in a different database, edited source record,
missing reference, malformed digest, BookDocument roundtrip, unchanged legacy progress
and failure before board activation. No proprietary decoder support is inferred.
