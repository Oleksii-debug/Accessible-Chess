# Media Intelligence + Universal Chess Agent Architecture

Status: **ACTIVE REQUIRED PRODUCT ARCHITECTURE**

Authority: `docs/CANONICAL_PRODUCT_VISION_AMENDMENT_2026-10-05.md`.

This document defines the public, implementation-safe architecture for synchronized chess media and the Universal Chess Agent. It intentionally excludes private commercial source/game-discovery heuristics while the repository is public.

## 1. Design goals

Accessible Chess should turn supported recorded/live chess media into an accessibility-first, synchronized chess experience:

- media playback and canonical chess state share a stable time/position mapping;
- NVDA can expose the move and current board even when the commentator does not speak notation;
- the user may pause and explore the exact position independently;
- user analysis does not destroy the media-synchronized cursor;
- one action restores the board to the current/last-paused media position;
- recorded media can be preprocessed into a durable timeline;
- live structured broadcasts can update the board directly through canonical validation;
- one Universal Chess Agent can query/control Board, GameTree, Engine, Library, Media and other application services.

## 2. Authority boundary

The canonical chain is:

```text
Media source
  -> provider/media adapter
  -> MediaSession + MediaClock
  -> typed MediaEvidence
  -> ChessStateReconciler
  -> canonical Board/GameTree
  -> MediaPositionTimeline
  -> Windows/NVDA presentation and Chess Agent
```

No vision/STT/AI/provider adapter owns chess legality.

Only existing canonical Board/GameTree/application services may publish accepted chess state.

## 3. MediaSession and MediaClock

`MediaSession` owns:

- stable session identity;
- provider/source kind;
- provider media ID/URL when policy permits;
- player state: unstarted/playing/paused/buffering/ended;
- duration/current timestamp where available;
- playback-rate/seek events;
- current media-synchronized GameTree cursor;
- session revision.

`MediaClock` converts player/provider time into one monotonic internal media timeline and tolerates pause, seek, buffering, reconnect and playback-rate changes.

The YouTube IFrame Player API is one possible playback adapter because the documented API exposes play/pause/seek/current-time/player-state operations. Provider-specific code remains outside canonical media/chess state.

## 4. Typed MediaEvidence

Evidence implementations may include:

- `StructuredMoveEvidence`;
- `BoardPlacementEvidence`;
- `StableFrameEvidence`;
- `SpeechContextEvidence`;
- `KnownGameCandidateEvidence`;
- `UserCorrectionEvidence`.

Every evidence item carries:

- source/provider;
- media time/range;
- confidence/reliability;
- source revision/version;
- provenance;
- raw candidate identity where safe.

Evidence is immutable input to reconciliation, not an accepted move.

## 5. BoardVisionPort

`BoardVisionPort` receives a provider-permitted image/frame and returns a board-placement candidate plus geometry/orientation/per-square confidence.

Rules:

- sample adaptively; do not require 30/60 FPS inference;
- distinguish transient/unstable animation or occlusion from stable positions;
- return uncertainty instead of fabricated pieces;
- never output authoritative side-to-move/castling/history without reconciliation.

Current reuse research candidate: `scoriiu/fenshot` (MIT), which provides board detection, 64-square classification, orientation handling and per-tile confidence with a small ONNX model. Adoption requires exact dependency/model/provenance review and our own fixture corpus.

## 6. SpeechContextPort

Where the source and provider policy permit speech processing, `SpeechContextPort` produces timestamped partial/final speech context.

It may detect candidate:

- player/tournament/opening names;
- spoken notation;
- commentary around the current media position.

Speech is context only and never publishes a legal move by itself.

Local STT implementations remain replaceable. Nika Core's optional specialist-worker boundary and implementations such as faster-whisper are reuse/research candidates, subject to exact dependency/model/license/resource evidence.

## 7. ChessStateReconciler

The reconciler is the reliability center.

Inputs can include:

- prior verified canonical position;
- canonical legal moves;
- current GameTree path;
- structured move candidate;
- stable board-placement candidate;
- temporal evidence;
- provider candidate line;
- permitted speech hints.

Outputs:

- `VERIFIED`;
- `INFERRED`;
- `OBSERVED`;
- `AMBIGUOUS`;
- `RESYNC_REQUIRED`;
- `NO_CHANGE`.

Required behavior:

- reject impossible positions/transitions;
- use canonical legal-move filtering before acceptance;
- if one legal transition uniquely explains a qualified observed delta, it may be accepted under explicit policy;
- if several legal transitions remain possible, wait for stronger evidence;
- match rewind to known ancestors where possible;
- model analysis branches as GameTree variations rather than corrupting one linear game;
- start a new media segment when the media genuinely jumps to an unrelated position;
- expose ambiguity to NVDA instead of silently guessing.

## 8. MediaPositionTimeline

Durable mapping:

```text
media timestamp/range
  -> media segment
  -> canonical GameTree path/node
  -> canonical position identity
  -> evidence qualification
```

Required operations:

- lookup state at timestamp;
- lookup timestamp(s) for GameTree node;
- next/previous media move;
- seek/rebind after media seek;
- rewind/variation traversal;
- timeline cache versioning;
- recognizer/provider version invalidation;
- restart/resume.

Recorded-media preprocessing can populate this timeline before or during playback.

## 9. Separate cursors: media vs user analysis

Media playback must not trap the user on a read-only board.

Maintain at least:

- `mediaCursor`: canonical position associated with player time;
- `analysisCursor`: user's temporary independent exploration/variation state.

`RestoreMediaPosition` discards or parks temporary analysis according to normal unsaved-work policy and restores `mediaCursor` without reconstructing moves manually.

## 10. Structured live broadcast adapter

Prefer structured chess data to computer vision when available.

The initial target should include Lichess Broadcast integration because Lichess currently exposes real-time broadcast PGN and a faster streaming API intended for third-party game streaming.

The adapter publishes structured move evidence; it still passes through canonical game/move validation.

Live media and structured feed may have different delays. A synchronizer estimates/maintains a media-to-feed offset so that media commentary and board position remain aligned.

## 11. Recorded-media preprocessing

A preprocessing job may:

- establish provider/media identity;
- collect permitted metadata;
- query provider-neutral structured candidate services;
- sample board-bearing frames;
- build stable board-position intervals;
- reconcile transitions/variations;
- attach permitted speech context;
- generate a durable `MediaPositionTimeline`.

The job must support progress, cancel, retry, restart and partial-prefix qualification.

## 12. Universal Chess Agent

Use one agent runtime and one tool registry.

Initial tool families:

- `board.*`;
- `gametree.*`;
- `engine.*`;
- `library.*`;
- `formats.*`;
- `books.*` / `training.*`;
- `media.*`;
- `speech_context.*`;
- `classroom.*`.

Example media tools:

- `media.status`;
- `media.play`;
- `media.pause`;
- `media.seek`;
- `media.current_position`;
- `media.next_move`;
- `media.previous_move`;
- `media.restore_position`;
- `media.context_around_current_time`.

Agent state-changing actions use the same application commands as human UI actions. No direct mutation of Board/GameTree/SQLite storage.

## 13. First-party reuse

Before custom agent infrastructure, inspect exact current donor revisions in:

- `Oleksii-debug/Nika-Core`;
- `Oleksii-debug/ChatGPT-Autopilot-ExtensionChatGPT-Autopilot-Extension`.

Reusable patterns include model routing, tool execution, durable jobs/checkpoints, cancellation/Stop, budgets and optional specialist workers.

Do not introduce a second orchestration authority inside Accessible Chess.

## 14. Provider compliance boundary

Provider adapters have a capability/policy state.

YouTube target:

- use documented embedded-player/Data API surfaces for playback/control/metadata;
- do not depend on downloading/caching audiovisual content;
- do not depend on undocumented stream extraction;
- do not separate/modify audio/video in a way prohibited by the current API policies;
- keep any uncertain frame/audio-derived processing behind a provider-compliance gate and obtain the needed provider approval/audit before commercial enablement.

Develop Media Core and deterministic fixtures independently with local/user-owned/permitted media so provider review cannot block the architecture.

## 15. Active Classroom allocation

Classroom remains a required product pillar, but near-term work should favor:

- shared canonical lesson/board state;
- teacher/student roles and permissions;
- synchronized position/GameTree;
- exercises/assignments;
- accessible teacher state;
- audio communication through a compliant replaceable provider when implemented.

Lower allocation priority unless an acceptance path requires them:

- simulated physical mouse;
- elaborate pointer/highlight/arrow visual polish;
- integrated video calls;
- friends/social play.

## 16. Acceptance

Media MVP is not complete without:

- deterministic known-timestamp/known-position fixtures;
- a linear recorded game case;
- rewind and side-variation case;
- pause/seek/rate-change case;
- transient animation/occlusion case;
- ambiguity that fails safe;
- structured live-broadcast case;
- restart/resume;
- NVDA/keyboard journey;
- Restore Media Position.

Agent MVP is not complete without:

- real typed application tool calls;
- Board/GameTree navigation;
- Stockfish request/result path;
- Library search/open path;
- media pause/seek/restore path;
- rejection of illegal/hallucinated mutations;
- cancellation/owner Stop;
- bounded provider/resource policy;
- no model dependency for canonical chess truth.

## 17. Public/private documentation boundary

This public document intentionally specifies contracts, not proprietary media-source/game-discovery heuristics.

Do not add private matching/ranking/source-order heuristics to this public repository without an explicit owner decision changing the repository/privacy policy.
