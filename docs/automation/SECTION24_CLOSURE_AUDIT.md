# Section 24 closure audit — Agent reliability, voice, privacy and resources

Canonical plan: **Section 24 — Agent reliability, voice, privacy і resource policy**.

## Accepted implementation

Canonical finisher PR: **#2434**.

Exact accepted candidate:

`fadf12059b941c61459870938027833fe51f21e1`

Integrated Agent authority:

`59eedf4e33de0565d0ad47d11206b6743dd3bff8`

Section 24 is closed sequentially after Section 23 in the same exact accepted
candidate/integration.

## Scope

- **24.1** `UniversalChessAgentRuntime.run()` accepts an exact
  `allowed_tool_ids` frozenset. A model-requested tool outside the allowlist
  raises before `ToolExecutor.execute()`, so hallucinated/unauthorized
  mutations cannot reach a handler.
- **24.2** `AgentVoiceConversation` composes replaceable async
  `SpeechInputAdapter` and `SpeechOutputAdapter` ports; it owns no audio
  provider, chess state or persistence.
- **24.3** `AgentPermissionPolicy` can only narrow registered tool authority;
  HIGH_IMPACT requires explicit opt-in in addition to the existing
  ToolExecutor approval/effect guards. Voice permission is rechecked before
  STT, before model use and before TTS. This module persists no recording,
  transcript, credential or provider secret.
- **24.4** `AgentResourcePolicy` reuses the existing owner/plan budget
  narrowing and fail-closed admission. Existing Universal Agent max steps,
  model-call ceiling, model timeout, ToolExecutor timeout, model-cost
  reservation/quarantine and cancel remain authoritative.
- **24.5** cancellation reuses the one Universal Agent runtime. The closure
  regression cancels a run after one atomic canonical write and before the next
  model step, proving the committed state remains valid and the write is not
  replayed.

## Safety invariants

- permission policy cannot invent an unregistered tool;
- child/plan resources cannot expand owner ceilings;
- voice provider receives no model text after live output permission revocation;
- model use is blocked if permission is revoked after transcription;
- cancellation does not synthesize rollback/replay of already committed
  canonical state;
- existing durable effect guards continue to own external/high-impact effects.

## Qualification and readback

Dedicated exact-head run **37684869279** registered Ubuntu 22.04 and Windows
2025 jobs. Both were queued/unstarted at integration; queued is **not GREEN**.
No executed Section-24 RED was known. Simplified Section Closure Protocol v3
therefore records hosted-runner unavailability rather than fabricating a PASS.

Post-merge candidate -> merge compare is ahead by one / behind zero with
**zero file delta**. Accepted source blobs were re-read byte-identically on
merge commit `59eedf4e33de0565d0ad47d11206b6743dd3bff8`.

## Terminal lock

`SECTION_24_STATE=DONE_TERMINAL`

Ordinary workers must not re-enter, reimplement, polish or repeat-audit Section
24. Reopen only for a concrete demonstrated regression, invalid closure
evidence, materially changed acceptance contract, or a later integration that
demonstrably breaks this closed scope.
