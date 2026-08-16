# Accessible Chess — Teaching, Classroom, Visual and Audio Product Specification

Status: foundation specification for parallel feature development. This branch must not be merged into a frozen Windows/NVDA release candidate until its own contracts are green and the current release P0 is closed.

## 1. Product goal

Accessible Chess must support both blind and sighted players and allow a blind coach to conduct a professional visual chess lesson without requiring mouse vision. The coach must be able to control visual teaching cues, demonstration positions, student boards, audio-room permissions, pairings and lesson material entirely from keyboard-accessible commands while sighted students see a polished board.

The feature family is intentionally split into neutral domain/application contracts and presentation/infrastructure adapters. The chess core remains the one authority for legal chess state. Visual themes, audio transport, classroom membership and teaching overlays must not become alternate chess-state owners.

## 2. Visual board and piece packs

### 2.1 Board themes

The UI must support installable board-theme packs. A theme is presentation only and may define:

- stable `theme_id`, title and version;
- light-square and dark-square appearance;
- optional border/background/selection/check/last-move colors;
- optional texture or gradient assets;
- high-contrast mode metadata;
- optional glow/animation metadata, respecting reduced-motion preferences;
- coordinate typography and contrast;
- attribution/license metadata for every third-party asset.

The board must scale without changing logical square identity. Board size is a user preference, not a chess-state property.

### 2.2 Piece themes

Piece sets must be independently selectable from board themes. A piece pack may provide SVG/PNG/WebP assets for all twelve piece/color combinations and metadata for preferred visual scale. Piece rendering must never replace accessible square names or keyboard semantics.

### 2.3 Coordinates

Support at least these coordinate modes:

- `off`: no visual coordinates;
- `edges`: conventional files/ranks around or inside the board edges;
- `every_square`: each square visibly carries its coordinate, useful in teaching beginners;
- later optional `teacher_only` / `student_only` projection for synchronized classrooms.

Coordinates are visual labels only. The accessible square name always remains the canonical coordinate even when visual coordinates are disabled.

### 2.4 Theme-pack installation

External packs must use a versioned manifest and a sandboxed asset directory. A pack installer validates:

- stable unique ID and schema version;
- all referenced files exist below the pack root;
- supported image types only;
- no path traversal;
- explicit license/provenance fields;
- no executable content;
- package size limits;
- safe fallback to a built-in theme if a pack is invalid.

Do not bundle unknown-provenance board/piece art. Prefer permissively licensed or original assets. Code license and art license are audited separately.

## 3. Sound system

The existing semantic sound events become a configurable sound-profile system rather than a single fixed set.

### 3.1 Required semantic events

Initial events:

- game start;
- move;
- capture;
- check;
- castle;
- promotion;
- illegal move;
- game end;
- clock tick / low-time warning.

Planned classroom/UI events may include participant joined/left, hand raised, teacher focus request, lesson position deployed and message/permission changes. Those must use separate UI/classroom event namespaces so chess event policy remains deterministic.

### 3.2 Per-event preferences

Each sound event must independently support:

- enabled/disabled;
- chosen sound within the active pack;
- per-event volume multiplier;
- preview button/command;
- optional repetition policy for warning events.

There is also a master enable and master volume. A disabled event must not fall back to the Windows system beep.

### 3.3 Sound packs

A sound pack is a versioned manifest mapping semantic event IDs to safe audio files. It carries title, author, license, version and optional descriptions. The resolver must reject unsafe paths and missing required assets. User packs may omit optional classroom events and inherit them from the built-in pack, but core chess-event behavior must remain explicit and testable.

## 4. Blind-coach visual pointer

### 4.1 Primary design

Do not make the operating-system mouse cursor the primary teaching mechanism. A dedicated synchronized `CoachPointer` overlay is more reliable, does not steal focus, can be announced to the blind coach, can be rendered consistently to every student, and works on Windows and future web/mobile clients.

The coach invokes a remappable command such as `teaching.pointer_input`. A compact edit field appears or receives focus. The coach types a square such as `f3`; as soon as a valid square is recognized:

1. input is committed;
2. the pointer/highlight moves to `f3` on the demonstration board;
3. the field clears automatically;
4. focus stays in the pointer field for the next coordinate;
5. a short accessible confirmation says `f 3`;
6. the classroom synchronization layer broadcasts the pointer target to students.

Typing `c7`, `a1`, etc. repeats with no Backspace cleanup.

### 4.2 Optional OS-cursor synchronization

An opt-in Windows adapter may physically move the mouse pointer to the center of the rendered square for presentation/recording compatibility. This is secondary and disabled by default because it can steal mouse position, interact with DPI scaling and produce accidental clicks. The semantic coach pointer remains the source of truth.

### 4.3 Pointer history for a blind coach

Whenever a student clicks, taps, focuses or explicitly points at a board square in classroom mode, emit a `StudentPointerEvent` containing participant ID/name, square and action type. The teacher presentation keeps a concise accessible current status plus a bounded history, for example:

`Марія: e 4.`
`Іван: c 6.`

No timestamp needs to be spoken by default. History is queryable and clearable. Pointer activity never changes chess position unless the participant also has move permission and completes a legal move.

### 4.4 Teaching annotations

The same overlay architecture must support later keyboard-first annotations without mouse dependence:

- highlight one square;
- arrow from source to target;
- clear last annotation;
- clear all annotations;
- named colors/styles;
- teacher-only versus shared annotation visibility.

A text command grammar can support forms such as `f3`, `f3 g5`, or explicit action prefixes, but it must not conflict with move-entry parsing. Teaching commands live in a separate context.

## 5. Lightweight identity without full accounts

### 5.1 Local profile

On first launch the app asks for a display name but permits Skip. If skipped, it creates a non-identifying alias such as `Учень 4821` / `Player 4821`. The user can change the display name later with a remappable command and Settings control.

Persist locally:

- stable random installation/profile ID;
- chosen display name or generated alias;
- language/accessibility preferences;
- theme/sound preferences.

Display name is not an authentication credential and need not be globally unique.

### 5.2 Classroom identity

When joining a class, the backend issues a room-scoped participant identity and transmits the display name separately. This allows duplicate human names while preserving unique network identities.

### 5.3 Usage statistics

Do not silently upload a child's full activity or chess content merely because the program was installed. Define a separate telemetry/statistics port with explicit policy and consent state.

Minimum useful aggregate events may include:

- app session started/ended and duration;
- games started/completed;
- puzzles/exercises attempted/completed;
- classroom attendance duration;
- feature-use counters.

Raw PGN, imported books/databases, typed chat/audio and exact lesson content are excluded by default. Classroom teacher/admin dashboards may record lesson-specific attendance and assigned-work progress under the explicit classroom relationship. The storage backend must keep a clear distinction between local-only profile data, room/session data and server-side administrative statistics.

For minors, deployment must support guardian/school consent and data-minimization policy before broad production telemetry is enabled. Recording audio is off by default and is a separate future capability requiring explicit policy and UI.

## 6. Audio classroom architecture

### 6.1 Transport

Use a mature WebRTC SFU rather than implementing conferencing transport from scratch. Preferred reuse candidate: LiveKit server, isolated behind an `AudioRoomPort` / `ClassroomRealtimePort`; TURN fallback may use LiveKit's TURN support or coturn. Video is disabled in the first product slice but the media contract remains source-aware so camera can be added later without redesigning room identity or permissions.

### 6.2 Room roles

Initial roles:

- teacher/host;
- co-teacher;
- student;
- observer.

Capabilities are explicit and server-authoritative where online:

- join/leave room;
- hear permitted participants;
- publish microphone;
- change own display name if allowed;
- move white/black/both/neither on a shared board;
- point/annotate if allowed;
- deploy lesson content (teacher);
- mute one/all (teacher);
- hard-lock microphone publication for one/all (teacher);
- remove/block participant from current room (teacher);
- grant/revoke move and annotation permissions.

### 6.3 Soft mute versus hard mute

Soft mute stops an existing microphone track. Hard mute changes participant publishing permission so the participant cannot simply re-enable the microphone until the teacher restores permission. UI must announce the distinction. A teacher action `Mute all and lock` revokes microphone publishing for students while preserving teacher/co-teacher audio.

### 6.4 Room lifecycle

A class can be created from a lesson plan or as an ad-hoc room. The teacher receives a join code/link. Accountless students may join through a short-lived invitation/token flow plus display name. Server secrets are never embedded in the desktop client.

The backend is authoritative for room membership and permissions. The desktop app must tolerate reconnects and must not duplicate moves when the network reconnects.

## 7. Lesson planning and reusable positions

### 7.1 Planned position

A `LessonPosition` stores:

- stable ID;
- human title;
- FEN;
- optional side-to-move/context note;
- optional expected task/question;
- tags/order;
- optional assignment target(s): all, group or specific participant IDs;
- optional teacher notes hidden from students.

Positions can be created from FEN, current board, position editor, a book/database position or imported PGN anchor. The shared chess/FEN validator validates playability; lesson storage does not invent chess legality.

### 7.2 One-action deployment

During a lesson the teacher selects a planned position and invokes `Deploy`. Depending on target:

- demonstration board changes for everyone;
- one selected student's board receives the position;
- a selected subgroup receives it;
- a pre-assigned batch deploys different positions to different students in one command.

Deployment must be reversible and logged in the lesson timeline. Student boards use stable assignment IDs so reconnect does not create a second assignment.

### 7.3 Lesson plan

A lesson plan may contain:

- title, target level and age band;
- objectives;
- planned time blocks;
- ordered explanation/demo items;
- planned positions;
- mini-games/exercises;
- pair-play block;
- recap questions;
- homework/next-step assignment.

This structure supports 1-to-1 and group lessons without forcing the teacher to improvise files during the live session.

## 8. Group pairing and supervised play

Teacher selects participants and creates pairings manually or automatically. Initial automatic pairing modes:

- sequential: 1–2, 3–4, 5–6;
- random;
- later rating/score-aware Swiss/ladder modes.

Each pairing assignment includes white participant, black participant, starting FEN, time control, increment, rated/unrated classroom flag and spectator/teacher access. Teacher can override colors before start.

Required class controls:

- start all boards;
- pause/stop all classroom games where supported;
- open any student's board instantly;
- cycle through active boards by keyboard;
- hear concise status: players, side to move, clock, last move and result;
- send a prepared position/task to one or more boards;
- return all students to demonstration mode.

Classroom games remain separate game sessions, never one shared mutable Board instance.

## 9. Pedagogy-driven teaching workflow

The software must directly support the recurring lesson pattern found in established child-chess curricula:

1. short warm-up/recall or puzzles;
2. one clearly bounded new concept;
3. coach demonstration on a shared board;
4. frequent questions and student participation;
5. worksheet/puzzle/guided practice;
6. mini-game or full game where the new idea is used;
7. observation and correction while students play;
8. brief recap/plenary and homework/next step.

For very young beginners, the product must support partial-board mini-games and learning pieces incrementally instead of assuming full-chess play from lesson one.

The teaching UI therefore needs one-key transitions between `Demonstrate`, `Ask/Point`, `Student control`, `Exercise`, `Pair play`, `Review` and `Recap` modes. These are orchestration modes over the same canonical board/data services, not separate chess implementations.

## 10. Accessibility requirements for teaching mode

The blind coach must be able to operate every teacher action without a mouse:

- open/close teaching pointer input;
- send pointer to square;
- create/clear annotations;
- read who is speaking/joined/left;
- read participant list and microphone state;
- mute/unmute/lock selected participant or all students;
- grant/revoke board control;
- select planned lesson position and deploy it;
- select one/all/group targets;
- create pairings and set colors/time control;
- open/cycle student boards;
- read student pointer/click history;
- read all confirmations/errors in concise live regions.

Sighted students receive a polished visual board, optional coordinates, theme/piece packs, pointer/highlight overlays and clear participant labels. Accessibility semantics are independent of visual theme assets.

## 11. Suggested stable action IDs

These are proposed contract IDs; final binding defaults remain remappable:

- `profile.rename`
- `teaching.pointer_input`
- `teaching.pointer_clear`
- `teaching.annotation_arrow`
- `teaching.annotation_clear_last`
- `teaching.annotation_clear_all`
- `teaching.student_pointer_history`
- `lesson.position.deploy`
- `lesson.position.deploy_assignments`
- `lesson.next_item`
- `lesson.previous_item`
- `classroom.participants`
- `classroom.mute_selected`
- `classroom.lock_mic_selected`
- `classroom.mute_all_students`
- `classroom.lock_all_student_mics`
- `classroom.grant_board_control`
- `classroom.revoke_board_control`
- `classroom.open_student_board`
- `classroom.next_student_board`
- `classroom.pair_students`
- `visual.coordinates_cycle`
- `visual.board_theme_next`
- `visual.piece_theme_next`
- `sound.profile_open`

No hard-coded F5 is required. If an F5-like default is desired for rename, it is registered through the central Action/Command Registry and remains remappable/conflict-checked.

## 12. Reuse-first decisions

- LiveKit is the preferred initial WebRTC/audio-room candidate because it provides an open-source multi-user SFU, client SDKs, JWT room permissions and moderation APIs. Keep it behind our port so another provider can replace it.
- coturn is a mature TURN/STUN fallback candidate for NAT traversal where needed.
- Existing chess.js/gchessboard-style projects may be used as differential or presentation references, but no external board becomes authoritative chess state.
- Any external board/piece art must pass a separate asset-license audit. Do not assume an MIT board library means all bundled artwork is MIT.

## 13. Delivery slices

Slice A — local visual/accessibility foundation:
- board/piece theme preference models;
- coordinate modes;
- theme/asset manifest contracts;
- coach pointer model and text-input contract;
- student pointer history model;
- sound profile/per-event preference model.

Slice B — local lesson foundation:
- saved LessonPosition and LessonPlan models;
- FEN/editor capture and deploy-to-demo-board;
- planned target assignments;
- keyboard-accessible teaching mode surface.

Slice C — classroom protocol foundation:
- participant/display identity;
- roles/permissions;
- room/session DTOs;
- board-control and pointer/annotation realtime messages;
- audio-room port, fake adapter and deterministic tests.

Slice D — online audio classroom:
- small backend for short-lived room tokens;
- LiveKit adapter;
- join/create UI;
- mute/hard-lock/remove/permissions;
- reconnect tests;
- audio-only production configuration.

Slice E — group orchestration:
- multi-student assignment/deployment;
- pairings/colors/time controls;
- cycle/open student boards;
- lesson timeline and progress summary.

Slice F — future video and advanced classroom:
- camera source permission;
- screen share if needed;
- richer annotations;
- recording only with explicit policy/consent;
- persistent accounts/class rosters when product is ready.

## 14. Release isolation rule

This feature family is developed in a separate branch/PR lane. Current critical Windows/NVDA release repair remains fail-closed. No unfinished classroom/audio/theme code is allowed to destabilize the candidate build. Passing slices may be merged to the main integration only when their architecture/tests are green and Worker Integration explicitly accepts them.
