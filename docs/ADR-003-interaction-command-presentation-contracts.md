# ADR-003: Explicit interaction command families and presentation state

Status: accepted on the non-release core work branch; no Stage 1 runtime integration.

## Context

Accessible Chess must use one chess core while supporting different input modes.
The text `e4` cannot carry intent by itself: Move Input, Teacher Pointer,
Position Editor, annotations, student hover, and student selection have different
semantics. Pointer, highlight, arrow, hover, and selection must not become a
second source of chess position truth.

## Decision

- `acs.squares` owns canonical square identity shared by every mode.
- `acs.interaction_contracts` defines distinct immutable message types for
  `MoveCommand`, `TeacherPointerCommand`, `PositionEditorCommand`,
  `AnnotationCommand`, `StudentHoverEvent`, and `StudentSelectionEvent`.
- Versioned payloads use an explicit `family` discriminator and reject unknown
  versions, families, missing fields, and extra fields instead of guessing.
- Student hover and selection remain events. They are never deserialized as
  moves. A future teaching policy may explicitly create a `MoveCommand`, but
  that conversion is outside these DTOs.
- `PresentationState` contains only pointer, highlights, arrows, coordinate
  visibility, student pointer history, active-student identity, board
  permission, and engine visibility. It deliberately contains no Position,
  FEN, move history, or legality implementation.
- Presentation contracts depend only on the canonical square primitive and
  standard-library types. They do not import UI, database, engine, or platform
  adapters.
- `acs.interaction_router` classifies effects before any adapter executes a
  message. A family/source mismatch is rejected with `effect=none`.
- `PositionEditorCommand.operation` is a bounded `PositionEditorOperation`,
  not adapter-defined text. Each operation has an exact field shape: clear,
  place/remove piece, side to move, castling, en-passant, move counters, or
  FEN load. Unknown operations and wrong field combinations fail closed with a
  stable contract error code before the router can grant mutation authority.
- The router revalidates a position-editor command at the authority boundary.
  Python class identity alone is not permission to mutate position state.
- Student hover and selection are always observation-only, even when the board
  policy allows moves. A student can create a chess move only by sending an
  explicit `MoveCommand` while `BoardPermissionState.MOVE_ALLOWED` is active.
- JSON Schema 2020-12 documents in `schemas/` and checked-in golden fixtures
  make the v1 boundary testable by non-Python adapters without duplicating
  chess rules or relying on prose-only contracts.
- Wire readers enforce the same scalar types and canonical lowercase square
  form as the schemas. They never coerce numbers, booleans, arrays, or objects
  into text and never normalize a non-canonical wire square silently.
- Checked-in negative conformance fixtures must fail in both the production
  readers and a JSON Schema 2020-12 validator.
- `InteractionRequest` binds each message to an explicit `InputSource` and
  `InteractionPolicy`. Its versioned request/decision payloads let adapters
  call one canonical routing policy instead of recreating family permissions.
- A rejected routing decision is structurally incapable of claiming a
  position-mutating effect in both Python and JSON Schema.
- Arrow start and end squares must differ. The shared
  `distinct-square-pair-v1.schema.json` encodes all 64 forbidden same-square
  pairs and is referenced by both annotation messages and presentation state,
  matching the Python command and state models.

## V1 pre-freeze compatibility decision

- Existing canonical payloads for `clear`, `place_piece`, and `set_turn`
  retain their field names and meaning when their operation-specific fields
  are valid.
- The remaining bounded editor operations use the same six-key payload shape;
  move-counter values are canonical decimal strings, preserving the original
  v1 scalar type while rejecting signs, whitespace, leading zeroes, booleans,
  floats, and adapter-specific numeric coercion.
- Arbitrary operation text was never a stable executable contract. Payloads
  that relied on unknown operations now fail closed instead of receiving
  mutation authority.
- Equal-square arrows were already rejected by the Python runtime. The schema
  correction narrows non-Python readers to that established behavior and does
  not reinterpret a valid Python-produced payload.

## Consequences

- Windows, Web, Mobile, and Teacher/Classroom adapters can exchange stable JSON
  payloads without duplicating chess rules.
- Current Stage 1 behavior is unchanged because no release UI path consumes the
  new contracts yet.
- Future adapters must route input through an explicit mode and may not infer
  move intent from coordinate text.
- Future position-editor adapters must consume the bounded operation enum and
  must not attach local meanings to unknown operation strings.
- A later contract revision must increment the version and provide an explicit
  migration path; v1 readers fail closed on unsupported payloads.
