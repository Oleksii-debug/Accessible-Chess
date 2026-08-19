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

## Consequences

- Windows, Web, Mobile, and Teacher/Classroom adapters can exchange stable JSON
  payloads without duplicating chess rules.
- Current Stage 1 behavior is unchanged because no release UI path consumes the
  new contracts yet.
- Future adapters must route input through an explicit mode and may not infer
  move intent from coordinate text.
- A later contract revision must increment the version and provide an explicit
  migration path; v1 readers fail closed on unsupported payloads.
