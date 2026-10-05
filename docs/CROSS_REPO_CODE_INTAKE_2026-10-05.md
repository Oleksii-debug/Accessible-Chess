# Cross-repository code intake — 2026-10-05

Status: active implementation evidence for the 2026-10-05 Media Intelligence + Universal Chess Agent scope.

This intake is intentionally limited to repositories owned by `Oleksii-debug`. It records code actually ported/adapted into Accessible Chess and repositories reviewed but not copied because doing so would create duplicate authorities or import unrelated product code.

## Integrated code

### Nika-Core

Exact donor repository head reviewed: `Oleksii-debug/Nika-Core@6df8b80b7a248f1559a0ff96f74efa2d2c47ad14`.

Code ported/adapted:

- media error taxonomy;
- privacy/secret redaction;
- bounded hashing;
- safe media subprocess runner with cancellation/resource fences;
- PCM WAV/FFmpeg normalization boundary;
- local-only faster-whisper and sherpa-onnx transcriber adapters;
- chunked transcription contracts/planning/merge semantics;
- ModelGateway contracts and provider fallback/privacy routing;
- agent task-state transition machine;
- fail-closed retry/backoff planning;
- ToolExecutor authority boundary.

Accessible Chess-specific adapters then bind those primitives to canonical Board/GameTree/AnalysisService/ACSDB rather than importing the Nika product runtime wholesale.

### AutoTrade

Exact donor repository head reviewed: `Oleksii-debug/AutoTrade@60e7c95b3b572810dcfb6c4ab34e0b338b0ace02`.

Adapted:

- exact-decimal model-call budget reservation/settlement semantics from `mvp/autotrade_mvp/model_gateway.py`.

Result: Universal Chess Agent has a provider-neutral cost ceiling before commercial model routing is selected.

### Autosport

Exact donor repository head reviewed: `Oleksii-debug/Autosport@bd1f603b769606027af409fa9a7e1385d774c4cf`.

Adapted:

- bounded accessibility announcement priority/deduplication policy from `src/autosport/accessibility_announcements.py`.

Result: high-frequency media/agent churn is suppressible, user-result events are polite, recovery/authority failures are assertive, and announcement policy never requests focus movement.

### ChatGPT Autopilot Extension

Exact donor repository head reviewed: `Oleksii-debug/ChatGPT-Autopilot-ExtensionChatGPT-Autopilot-Extension@fc62b45985654930dfa0e474b01e5e3a03bbfdf4`.

Adapted into Python rather than importing browser-extension JavaScript:

- least-authority model/tool orchestration principle;
- bounded model -> tool -> result -> model execution loop;
- cancellation/Stop semantics;
- strict JSON model action envelope;
- checkpoint material binding;
- effect-ledger rewind fence: internal state may be reconciled after restart, but completed/unresolved external effects are not silently replayed or rolled back.

### 12-6-ai

Exact donor repository head reviewed: `Oleksii-debug/12-6-ai.@019944d5fe12334791f05f1232d13de4a12e37d3`.

Ported:

- generic identity-pinned directory primitive from `src/twelve_six/checkpoint/pinned_directory.py`.

Result: media publication critical sections stay bound to the opened directory identity rather than trusting a replaceable pathname.

### WordDeck

Exact donor repository head reviewed: `Oleksii-debug/WordDeck@3b048fd0909b443ffd561fdf13faff711a8186ea`.

Reused safety pattern from `src/worddeck/backup.py`:

- publication is no-replace, not check-then-`os.replace`;
- a concurrent destination must never be clobbered;
- uncertain publication fails closed.

Accessible Chess applies the pattern to media artifact promotion using an atomic no-replace hard-link publication inside the pinned root rather than importing WordDeck database recovery wholesale.

## Accessible Chess bindings added

New Accessible Chess-owned product code includes:

- `media_foundation.py`: MediaSession/MediaClock, typed evidence, ChessStateReconciler, MediaPositionTimeline;
- `chess_agent_tools.py`: concrete Board, Stockfish AnalysisService, ACSDB/Library and Media tools;
- `universal_chess_agent.py`: bounded model/tool agent loop over ModelGateway + ToolExecutor;
- `agent_budget.py`, `agent_retry.py`, `agent_checkpoint.py`;
- `assistive_announcement.py`;
- media process/audio/transcription/transcriber infrastructure.

The media reconciler preserves the canonical rule: structured/vision/speech/model evidence cannot mutate Board/GameTree without canonical chess validation.

## Repositories reviewed without direct code copy

### Nika-agent

Head reviewed: `f6534948b021f77a7035e722501ad78c54b6b9b4`.

Its useful orchestration behavior is browser/TypeScript-oriented and overlaps with stronger Python contracts already taken from Nika-Core. Importing it would create a second browser-orchestration authority, so no direct copy is justified.

### Telegram-ChatGPT-Bridge

Head reviewed: `f755c36b13ce0f5cc3151f07a9f1712c40934aec`.

Relevant recovery material is operational/server shell work rather than reusable Accessible Chess desktop/media/agent runtime code. No direct product-code intake.

### scripture-archive

Head reviewed: `a7a27f77750058055c5726d1ff9c7fbfa928da3d`.

No generic media/agent runtime implementation stronger than already selected donors was found. Domain-specific scripture code is not imported into chess.

### ChatGPT-Deep-Research-Shortcut

Head reviewed: `50646484daa410f2cd1e4139817c9959ac046854`.

Automation-specific behavior does not improve the selected Python ModelGateway/ToolExecutor/agent runtime boundary. No direct copy.

### AudioTacticalFPS

Head reviewed: `576c60ad86bae377cf5645908ad18e2c86aa72b8`.

No substantive reusable media/agent runtime source was found beyond repository coordination material. No direct copy.

## Anti-duplication rule

This intake does not authorize importing two competing storage, chess-rules, model-routing or orchestration authorities.

Existing Accessible Chess owns:
- chess legality/Board/GameTree;
- ACSDB/Library;
- AnalysisService/Stockfish semantics;
- Windows/NVDA presentation.

Donor code is adapted behind those authorities.

## Qualification

The integration branch is `work/media-agent-crossrepo-intake-20261005`, based exactly on product head `0a92698bbb923ef6d7bc2d672e3fd30554fb0138`.

The intake is not considered integrated merely because source files exist. Focused regression tests and repository CI must pass, and any failures must be repaired before merge.
