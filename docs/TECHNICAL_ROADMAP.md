# Accessible Chess — Technical Roadmap derived from Canonical Product Vision

Canonical product vision: `docs/CANONICAL_PRODUCT_VISION_UA.md`.
Binding platform amendment: `docs/CANONICAL_PRODUCT_VISION_AMENDMENT_2026-09-04.md`.
Binding Web/server architecture: `docs/WEB_PRODUCT_ARCHITECTURE.md`.

This roadmap does not replace the canonical vision. It translates it into architectural dependencies and delivery gates.

## 1. Non-negotiable product invariant
Accessible Chess is one professional accessibility-first chess platform for blind and sighted users, including a blind coach teaching sighted children. Accessibility is not a reduced mode. Visual presentation is not a second source of chess truth.

The Windows/NVDA desktop edition remains a first-class standalone product. The 2026-09-04 user amendment additionally makes an accessible Web edition a first-class end-state product surface. Windows and Web must share one canonical chess/application truth.

## 2. One canonical chess core
All modes and clients consume the same canonical domain/application layer:
- Position / board state;
- Move / legality / attack map;
- SAN / FEN;
- Game / Result;
- GameNode / GameTree / Variation;
- comments / NAG / annotations;
- history/review/undo/redo;
- engine request/result models;
- source provenance and versioned serialization.

Windows/NVDA, Web, mouse/visual board, Teacher Board, Classroom, PGN, ACSDB, ChessBase adapters and books must not implement separate chess rules.

## 3. Separate command families
The application must never infer user intent from ambiguous text. At minimum keep distinct command families:
- MoveCommand: `e4` means make a chess move only in Move Input mode;
- TeacherPointerCommand: `e4` means point at square e4 only in Teacher Pointer mode;
- PositionEditorCommand: editing a piece/state is not a move;
- AnnotationCommand: highlight/arrow/marker does not mutate Position;
- StudentHoverEvent: presentation feedback only;
- StudentSelectionEvent: answer/selection, and becomes a move only in a mode that explicitly permits a move.

These command/event families should remain serializable and platform-neutral where practical so Windows and future Web adapters can call the same application services.

## 4. Presentation state is separate from chess state
Teacher pointer, visual cursor, highlights, colors, arrows, coordinate labels, hover history, selected student and engine visibility are presentation/session state. They reference canonical squares/positions but do not become chess truth.

Suggested durable models/interfaces (reuse repository equivalents where they already exist):
- PresentationState;
- TeacherPointerState;
- BoardAnnotation / VisualArrow / SquareHighlight;
- StudentPointerEvent / StudentSelectionEvent;
- LessonSession / TeachingSession;
- InputPolicy / BoardPermissionState;
- EngineVisibilityPolicy.

Platform-specific presentation code belongs in adapters. Durable session identities and state transitions must not depend on a local Windows control instance.

## 5. Stage 1 — Windows/NVDA foundation and release gate
Current Stage 1 remains governed by Issue #14 and human acceptance Issue #22. Required foundation includes Windows standalone app, 64-square accessible board, Move Edit, Position Explorer/Editor, history/review/undo/redo, keymap, notation, real sounds, native menu, Stockfish, packaged E2E and fresh exact NVDA candidate.

No human-rejected ZIP is reused. `NVDA_VERIFIED=NO` until Oleksii personally tests the exact fresh candidate.

The architecture must preserve future Teacher/Classroom/PGN/Database/Books/Web paths, but Stage 1 release lineage stays narrow.

## 6. PGN + canonical GameTree
Dependency: canonical chess core.
Required capability:
- full PGN tags/result/move numbers;
- SetUp/FEN;
- comments;
- NAG;
- nested RAV;
- arbitrary branch depth;
- mainline promotion/reordering;
- deterministic parent/return semantics;
- multi-game PGN;
- safe malformed-input handling;
- round-trip preservation tests.

GameTree is the interchange model for PGN, databases, books, student-game review, ChessBase imports and future server/Web transport. Web payloads must not invent a second tree model.

## 7. ACSDB / Library / Search
Dependency: GameTree + provenance.
Schema must scale beyond games to positions, GameTrees, comments, variations, books, exercises, students, courses, assignments and metadata without binding domain logic to SQLite or one device.

Capabilities:
- safe versioned migrations and rollback strategy;
- games/players/events/sources/ECO;
- dedupe with provenance;
- metadata and position search;
- library browsing/filtering/export/import;
- progress/cancellation for long imports;
- no silent data loss.

Current desktop storage may remain local. Canonical entities must use durable identities and versioned serialization so future cloud Library synchronization/storage can be added without redesigning chess semantics.

## 8. ChessBase compatibility
Dependency: canonical GameTree + provenance + import reporting.
Formats of interest: CBH, CBV, CBF and related supported families as technically/legal feasible.

Hard boundary:
`ChessBase source -> format adapter -> canonical GameTree/metadata/provenance -> ACSDB/PGN`.

ChessBase internal records must not leak into UI, books, database or Web APIs.
External source files are read-only by default.
Every adapter exposes explicit capability/support status and an ImportReport. Never invent data and never claim lossless support without evidence.

## 9. Accessible Books and training content
Dependency: canonical Position/GameTree and Library.
A book is semantic content, not only formatted text or image diagrams.

Canonical book/training blocks should be able to represent headings, paragraphs, positions, structured diagrams, games, variation trees, exercises and notes. A position from a book can open in Board Explorer/Stockfish/Teacher Board and return to the original reading context.

Books can become sources for assignments/exercises without copying chess logic.

BookDocument, BookReader and progress identities should remain usable from either Windows or a future authenticated Web client.

## 10. Teacher / Classroom mode — central product pillar
This is not a minor visual add-on. The target is a blind coach operating keyboard/NVDA or equivalent accessible Web controls while sighted children receive a modern visual lesson.

### Teacher visual pointer
A dedicated pointer editor is distinct from Move Input.
Example contract:
- teacher invokes pointer editor;
- types `f3`;
- as soon as a valid coordinate is complete, presentation pointer moves to f3;
- input clears automatically;
- teacher immediately types the next coordinate without Backspace or extra confirmation.

Implementation need not move the physical Windows mouse. A large marker/ring/frame/animated pointer is acceptable and often better.

### Visual board and annotations
- themes, colors, size, orientation, coordinates;
- selected piece and last move;
- keyboard-driven square highlight;
- legal-move highlight based on real legality (green may be default, configurable);
- attacked/defended/target/multi-square highlight modes;
- multiple visual arrows such as `e2 -> e4`, with one-command clear;
- coordinate-label toggle.

### Reverse channel from sighted student
Student mouse hover and click/selection are distinct events.
Teacher receives concise accessible feedback such as square and piece description.
Maintain accessible student-pointer history in order, e.g. f3, e5, d4, c6.

### Teaching interaction modes
- Teacher Explains: teacher owns position; student cannot mutate it accidentally;
- Student Responds: student may select piece/square or make a move according to explicit policy;
- Show Square;
- Show Piece;
- Make a Move;
- Where Can This Piece Move;
- Attack/Defence tasks;
- solution reveal controlled by teacher/exercise policy;
- optional timer, not mandatory for young children.

### Teacher Board
Can load start position, FEN, PGN, book position or database position, edit pieces, traverse variants, reset, annotate and use Stockfish. It is not necessarily a live game.

### Engine visibility policy
Separate states:
- visible to teacher;
- visible to student;
- hidden.

## 11. Classroom, students, courses and assignments
Dependency: TeachingSession + Library + GameTree + ACSDB.
Future models must support:
- class/group/course/cohort;
- student identity/name or pseudonym;
- level and optional rating;
- lessons and lesson material;
- exercises;
- assignments/homework;
- student games and review;
- group and individual sessions;
- progress and results;
- privacy/consent/data-minimization/deletion requirements before real personal-data collection.

Lesson material may contain positions, explanations, questions, games, variations, exercises and homework with Next/Previous traversal.

These entities must have explicit ownership/identity semantics suitable for a future authenticated server without forcing local-only Windows paths into canonical records.

## 12. Online / remote lessons
Dependency: deterministic commands/events and stable identities.
Teacher and student may have different presentation surfaces over one synchronized canonical session.
Synchronize position, teacher pointer, annotations and student hover/click/answers. Group mode supports one shared teacher board, active student and individual answers.

The future preferred delivery is a true accessible Web client/server session, not a streamed remote Windows desktop. A blind teacher may use Windows/NVDA while students use browser clients, or the teacher may also use the Web client if accessible.

## 13. Accessibility completion rule
A feature is not complete if it is mouse-only. For every important function check keyboard-only operation, focus, accessible names/state/errors, screen-reader semantics and standard clipboard/menu behavior where applicable.
Visual features must have a meaningful text/NVDA equivalent for the blind teacher/user.

Windows and Web accessibility are separate acceptance surfaces:
- `NVDA_VERIFIED` applies only to the exact Windows candidate tested by Oleksii;
- future `WEB_ACCESSIBILITY_VERIFIED` requires real browser/screen-reader testing of the exact Web candidate.

## 14. Web-ready application boundary
From 2026-09-04 onward, new domain functionality must avoid direct coupling to Windows controls.

Preferred flow:

`presentation adapter -> command/query DTO -> application service -> canonical domain/storage/runtime -> result/event -> presentation adapter`

Requirements:
- common command/query semantics for Windows and Web;
- serializable durable IDs where practical;
- no absolute local Windows path as a cross-platform identity;
- explicit user/workspace/session ownership for future remote features;
- server-side validation for future state-changing Web requests;
- progress/cancel/retry/restart semantics for long operations;
- platform-specific file pickers/process launching remain adapters.

Contract tests should eventually prove that the same canonical application action can be invoked through a local Windows adapter and a test Web/server adapter without duplicated chess logic.

## 15. Web/server/commercial product stage
This stage is future work after the active desktop/formats release gates; it is not a reason to stop current Version 2 delivery.

Dependency: stable application boundary + durable identities + canonical Library/Teacher semantics.

Required capability sequence:
1. minimal authenticated server adapter over real application commands/queries;
2. accessible read-only Web shell over real canonical data;
3. interactive board and GameTree;
4. account/workspace isolation;
5. cloud Library/progress;
6. server or policy-selected analysis workers;
7. Teacher/Classroom synchronization;
8. subscriptions/entitlements and quotas;
9. multi-tenant security/threat-model gates;
10. Web accessibility acceptance;
11. staged production deployment/rollback.

The browser is untrusted for entitlement/security truth. Premium access, ownership and permission decisions must be validated server-side. Payment/provider secrets must never be embedded in browser code.

## 16. Delivery strategy
- Keep current Stage 1/Version 2 release lineage narrow and evidence-driven.
- Preserve the full Windows + Web product vision in architecture/backlog even when a feature is not in the current release.
- Build current functional work in dependency order: GameTree/PGN -> ACSDB/Library -> ChessBase adapters -> Books/Training -> Teacher/Classroom -> Online/remote lessons.
- Web product implementation follows after stable shared application contracts; do not maintain two rapidly changing full UIs in parallel prematurely.
- Difficult adapters are replaceable boundaries. A blocked CBH decoder must not require redesign of GameTree/ACSDB/Books/Teacher UI/Web API.
- Use explicit capability states such as SUPPORTED/PARTIAL/UNSUPPORTED/BLOCKED and never silently invent or drop data.
- Future commercial Web work must not weaken the standalone Windows/NVDA product or make ordinary desktop use require a cloud subscription unless a later explicit product decision says so.

## 17. Release/accounting truth
Keep these states separate:
- Windows current release readiness;
- Version 2 formats/library readiness;
- Teacher/Classroom readiness;
- WEB_ARCHITECTURE_READY;
- WEB_API_READY;
- WEB_UI_FOUNDATION_READY;
- WEB_AUTH_SECURITY_READY;
- BILLING_ENTITLEMENTS_READY;
- WEB_ACCESSIBILITY_VERIFIED;
- WEB_PRODUCTION_READY;
- HUMAN_TESTED;
- NVDA_VERIFIED.

Existing WebView use inside the Windows application does not count as a Web product.
