# Canonical Product Vision Amendment — Active Media Intelligence and Universal Chess Agent

Status: **BINDING OWNER DIRECTION / ACTIVE IMPLEMENTATION SCOPE**

This amendment is binding alongside `docs/CANONICAL_PRODUCT_VISION_UA.md`,
`docs/TECHNICAL_ROADMAP.md`, and `docs/WEB_PRODUCT_ARCHITECTURE.md`.

## 1. Scope promotion

The following capabilities are no longer distant backlog or "final-stage only" ideas:

- Media Intelligence for recorded and live chess media;
- synchronized media timestamp <-> canonical Board/GameTree state;
- structured live-broadcast integration;
- replaceable board-vision and permitted speech-context workers;
- one Universal Chess Agent that can use typed Accessible Chess application tools;
- simplified Classroom core where it provides concrete teaching value.

Older wording that says the AI Coach/Agent must not be implemented now is superseded by this amendment.

Formats / Library / ChessBase remain release-critical. This amendment does **not** stop or replace that work. It authorizes parallel work so a free worker does not need to wait for another owned lane to finish.

## 2. Product allocation direction

Current high-value product lanes include:

1. Formats / ACSDB / Library / ChessBase correctness, real-corpus qualification, Windows/NVDA acceptance.
2. Media Intelligence and synchronized accessible board.
3. Universal Chess Agent over the canonical product.
4. Simplified Classroom/teaching core, including synchronized lesson state and audio communication where appropriate.

This is an allocation guide, not a serial dependency checklist. A worker may take any unowned actionable lane.

Presentation-heavy Teacher pointer/simulated-mouse behavior, elaborate highlight/arrow polish, integrated video calling, and social/friends-play features may be deferred unless they are required by an already-owned acceptance path.

## 3. Media contract

The target experience is:

- open/associate a supported recorded or live chess-media source;
- maintain a canonical synchronized position and GameTree cursor;
- advance/reposition the Accessible Chess board as media position changes;
- expose move/state changes through keyboard/NVDA;
- allow the user to pause media and independently explore the position, create analysis variations, use Stockfish or Library, or ask the Agent;
- preserve a separate media-synchronized cursor;
- provide one **Restore Media Position** action that returns to the exact position corresponding to the current or last-paused media timestamp;
- seek backward/forward and rehydrate the corresponding canonical timeline state;
- for recorded media, persist a qualified timestamp-to-position/GameTree timeline so repeated playback does not require full re-recognition.

## 4. Canonical truth and evidence

Media evidence is not chess truth.

Provider data, computer vision, OCR, speech recognition, metadata, Internet results, and AI output are typed evidence only. They may propose candidates but must never mutate canonical Board/GameTree state directly.

A dedicated Chess State Reconciler validates candidates against canonical legality/history and emits explicit states such as:

- OBSERVED;
- INFERRED;
- VERIFIED;
- AMBIGUOUS;
- RESYNC_REQUIRED;
- NO_CHANGE.

When an authoritative structured chess feed is available, it should be preferred to vision for move truth.

## 5. Universal Chess Agent

Accessible Chess must have **one universal tool-using Chess Agent**, not disconnected AI features.

The Agent uses typed application services for Board, GameTree, Stockfish, Library/Database, Formats, Books/Training, Media, and Classroom. It does not scrape the product UI and does not implement a second chess engine/rules system.

Example requests include:

- "Pause. What did the commentator just show?"
- "Why is this move strong?"
- "Put this alternative on my analysis board."
- "Return to the media position."
- "Find this position in my Library."
- "Compare the commentator's idea with Stockfish."
- "Go to the moment before the mistake."
- "Create an exercise from this position."

Every state-changing tool call remains subject to canonical validation, durable identity, cancellation, permissions and resource policy.

## 6. Cross-project reuse

Before inventing generic agent infrastructure, inspect first-party reusable contracts in Nika Core and ChatGPT Autopilot under the existing cross-project reuse policy.

Reuse/adapt stable patterns such as:

- observe -> reason -> tool -> verify;
- ModelGateway/provider abstraction;
- tool registry/executor;
- durable job/checkpoint state;
- cancellation and owner Stop;
- bounded retry and resource/cost policy;
- optional specialist vision/speech worker boundaries.

Do not embed an entire unrelated agent product into Accessible Chess. Chess-specific state and tools remain owned by Accessible Chess.

## 7. Provider compliance

Media core is provider-neutral.

For third-party platforms, use documented/authorized APIs and respect provider content policies. Do not make downloading, undocumented stream extraction, prohibited caching, or prohibited audio/video separation a product dependency.

The YouTube integration target may use documented embedded-player and metadata APIs, but any frame/audio-derived processing that is not clearly permitted remains a provider-compliance gate before commercial enablement.

This compliance gate must not block implementation of generic MediaSession, MediaClock, MediaPositionTimeline, ChessStateReconciler, Universal Chess Agent, local/user-owned media test paths, or structured broadcast integrations.

## 8. Confidential product logic

The current repository is public. Implementation-specific commercial heuristics for source/game discovery and synchronization are deliberately **not documented publicly**.

Public code/docs should expose stable interfaces and testable contracts. Private product strategy remains in the owner's private project records.

## 9. Worker law

Workers are explicitly authorized to implement this scope now.

- refresh live repository ownership before coding;
- do not duplicate an active branch/PR;
- if the original workline is complete or genuinely blocked, continue with another highest-value unowned active lane;
- preserve new product semantics in repository docs/tests rather than only in chat history;
- do not claim media/agent completion from a demo without deterministic fixtures, error/ambiguity handling and NVDA/keyboard acceptance.
