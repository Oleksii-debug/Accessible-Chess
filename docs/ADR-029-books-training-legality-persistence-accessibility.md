# ADR-029: Legal books/training workspace and ACSDB v4 invariants

Status: accepted for the product books and local-training vertical.

## Context

The v1 BookDocument, BookReader, and training contracts established typed
presentation-neutral DTOs, but they did not prove that embedded PGN or exercise
moves were legal from their declared positions. Reading locations were only
in-memory indexes, training snapshots did not preserve the chess line, and the
release composition had no durable books, bookmarks, definitions, or progress.

Those gaps could produce false trust: a plausible PGN string, stale bookmark,
or counter-consistent training snapshot could become product state without an
exact legal reconstruction. The Stage 1 surface also needed a safe way to open
book positions and completed exercises in the already shared Stockfish
workspace without losing the user's live game.

## Decision

1. `BookDocument` writes schema v2 and boundedly reads v0/v1/v2. All position
   FEN passes the shared canonical chess-core validator. Embedded Game,
   VariationTree, and Exercise PGN must be exactly one lossless legal GameTree;
   variation and solution lines are linked from the exact declared root FEN.
   A PGN FEN tag is trusted only with `SetUp "1"` and must equal that root.
2. Canonical FEN validation is shared by books, training, and GameTree legality.
   It checks exact field/counter/castling spelling, structural board validity,
   side-not-to-move legality, and en-passant provenance before returning trusted
   text. Four-field FEN remains a legacy BookDocument input only.
3. BookReader owns an immutable semantic snapshot. A durable reading location
   binds book identity, snapshot SHA-256, exact block identity/source anchor,
   heading/chapter context, and a validated character offset. Restore is
   fail-closed and atomic; it never falls back by approximate title or index.
4. Opening a book chess block creates an isolated context with an exact return
   point. Self-contained positions, diagrams, exercises, variation trees, and
   PGN games are supported. A Game that references ACSDB by `game_id` resolves
   through the canonical stored GameTree and undergoes legality validation
   again before it reaches the board.
5. ExerciseDefinition writes a strict v1 definition. Every accepted move is
   replayed by the shared Board over every reachable prior solution position
   and stored as canonical SAN. Step count, branch width, reachable positions,
   and link operations have explicit safety limits.
6. ExerciseSession writes snapshot v2 with the exact canonical move history,
   current FEN, aggregate and current-step counters, reveal state, and status.
   Restore replays every move and compares the reconstructed FEN. Legacy v0/v1
   snapshots remain readable only when their completed line is unambiguous.
7. Solution reveal is policy-controlled (`never`, `after_attempt`,
   `after_hint`, or `anytime`). The presentation projection never exposes
   future accepted moves before a permitted explicit reveal. Stockfish analysis
   is allowed only after completion and only when the definition permits it.
8. ACSDB schema v4 adds books, exact bookmarks, exercise definitions, and
   progress. Canonical JSON and SHA-256 bind stored payloads to their summary
   columns. A changed book invalidates stale bookmarks; a changed definition
   deletes incompatible progress. Every read revalidates the complete payload.
9. The packaged release owns one persistent ACSDB beside user settings. The
   semantic WebView and native Library menu expose keyboard-operable book and
   training actions through the central registry. They reuse the existing
   board, history, and one production Stockfish provider rather than creating a
   second chess or engine state.
10. Entering a book chess block or exercise captures the exact live chess
    workspace. Return/close restores board, history, review cursor, and analysis
    enabled state. Training cannot mutate the live game or start engine play;
    analysis unlocked after completion remains confined to the exercise and is
    reconciled with the prior analysis state on close.

## Consequences

Books, bookmarks, legal exercises, progress, and post-completion analysis now
form one durable product path. Imported JSON is size-bounded before parsing;
database rows and references fail closed when missing, stale, corrupt, or
semantically illegal. All user-facing failures are concise and do not expose
Python exceptions, database text, or executable paths.

ADR-006, ADR-007, and ADR-008 remain the historical v1 foundations; this ADR
supersedes their schema/release-boundary statements where v2/v4 product behavior
is defined.

Automated tests cover legal reconstruction, snapshot tampering, bookmark
identity, migrations, persistent progress, solution secrecy, exact workspace
return, database-linked games, WebView semantics, keymap generation, and native
menu routing. This change does not modify the QA-owned Windows harness and does
not claim human NVDA verification. `NVDA_VERIFIED` remains `NO`.
