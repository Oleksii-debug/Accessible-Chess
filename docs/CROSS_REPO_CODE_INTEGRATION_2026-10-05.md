# Cross-repository code integration — 2026-10-05

Status: active implementation branch `work/media-agent-crossrepo-reuse-20261005`.

Purpose: reuse first-party code already developed in Oleksii-debug repositories instead of re-implementing generic infrastructure. This pass uses only Oleksii-debug repositories. No external repository source code is copied here.

## Ported / adapted code

### Nika-Core

Donor files:
- `src/nika_core/runtime/contracts.py` blob `03191b2ef23eabd9274aee98c9c02c1b6e784aac`
- `src/nika_core/runtime/retry.py` blob `64da65c4f96c2a4cb8e0e3f63e8af92054c81193`
- `src/nika_core/tools.py` blob `5df4992ca8645511e7d3fa4e976d884be3b9faa2`
- `src/nika_core/model_gateway/contracts.py` blob `bafcf6cbb07d5b511979b09d1d920972a00da2c2`
- `src/nika_core/model_gateway/gateway.py` blob `cff342b529121e73d549f99398c1c333b57524d8`
- `src/nika_core/media/audio.py` blob `2a305f0d0edbf9c6a99d0eaac11e1dd9c5d1ca50`
- checkpoint patterns from `src/nika_core/kernel/checkpoint.py`.

Accessible Chess destinations:
- `acs/agent_runtime.py`
- `acs/agent_tools.py`
- `acs/agent_model_gateway.py`
- `acs/media_audio.py`
- `acs/durable_checkpoint.py`

Adaptation policy: remove Nika-specific persistence/audit/process dependencies; retain strict contracts, cancellation/retry semantics, canonical argument hashing, privacy-aware model routing and bounded WAV inspection. Chess legality remains owned by Accessible Chess.

### AutoTrade

Donor files:
- `mvp/autotrade_mvp/model_gateway.py` — exact budget ledger/model-cost ideas.
- `mvp/autotrade_mvp/accessibility.py` blob `046b151ce0f61d73718c1ca0b66c33cc6368ce04`.

Accessible Chess destinations:
- `acs/agent_budget.py`
- `acs/agent_accessibility.py`

Adaptation policy: remove trading/economic-domain authority and journal coupling. Preserve exact Decimal budget accounting and stable plain-text screen-reader status.

### 12-6-ai.

Reusable donor pattern: canonical JSON/hash and fail-closed checkpoint durability from the checkpoint subsystem.

Accessible Chess destination:
- `acs/durable_checkpoint.py`

Adaptation policy: no ML trainer, model weights, RNG, NumPy/PyTorch, or training-specific checkpoint state is imported. Only dependency-free canonical JSON/hash durability is reused.

### Telegram-ChatGPT-Bridge

Donor branch: `final10/a1-canonical-successor-20260830`.

Donor:
- `bridge/errors.py` blob `c59ad5c5d64747d3f9084c9d8fa2b09446342e43`.

Accessible Chess destination:
- `acs/public_errors.py`

Adaptation policy: retain bounded public error codes/status/details and CR/LF/control-character fail-closed behavior for future Web/media/agent adapters.

### Nika-agent

Donor branch: `dev/runtime-consolidated-candidate`.
Donor:
- `src/runtime.ts` blob `5f990821549f20d174a153ba3e2435544eb65099`.

Accessible Chess destination:
- `acs/keyed_async_lock.py`

Adaptation policy: reuse the per-agent exclusive-operation pattern as a Python per-identity async lock so one media session/agent thread serializes its control actions while independent identities stay concurrent. Browser/ChatGPT tab automation is not imported.

### ChatGPT-Autopilot-ExtensionChatGPT-Autopilot-Extension

Donor:
- `src/core/universal-agent-contracts.js` blob `5fbf0b87a7f6696034d4159b553d27c2a1425a3b`
- `src/core/agent-budget-admission.js` blob `b6559a49247e89bc7c281b2fe5df25e505ea6bbc`.

Accessible Chess destinations:
- `acs/agent_verification.py`
- `acs/agent_resource_budget.py`

Adaptation policy: preserve the distinction between observation and verification plus the invariant that plan/child resource authority can only narrow the owner ceiling. Browser/remote-agent/provider-specific code is not imported.

### Autosport

Donor:
- `src/autosport/accessibility_announcements.py` blob `21621bca6fbe29d0999b3a1286bf2f164f414808`.

Accessible Chess destination:
- `acs/assistive_announcements.py`

Adaptation policy: retain bounded history, product-owned event priority, stable activity identities, critical-episode deduplication and the invariant that announcement policy never moves focus. Replace market/sports event taxonomy with Media/Agent events.

### ChatGPT-Deep-Research-Shortcut

The owner repository currently exposes no implementation files on `main`; no reusable source was available to transplant in this pass.

## Accessible Chess-owned implementation added on top

`acs/media_core.py`, `acs/media_application.py`, and `acs/universal_chess_agent.py` implement the product-specific composition required by the 2026-10-05 owner amendment:
- MediaApplicationService delegates synchronized-position publication to an injected canonical application callback and owns separate media/analysis cursor state;
- UniversalChessAgentTools binds the reused tool executor to the existing Accessible Chess BoardCommandService and MediaApplicationService;
- no duplicate chess rules are introduced.

The provider-neutral media contracts include:
- MediaSession;
- typed MediaEvidence;
- ChessStateReconciler;
- MediaPositionTimeline;
- deterministic VERIFIED / INFERRED / OBSERVED / AMBIGUOUS / RESYNC_REQUIRED / NO_CHANGE semantics.

It is not copied from another repository. It composes the reusable donor primitives with Accessible Chess canonical chess authority.

## Reuse candidates intentionally NOT copied in this pass

### Nika-Core idempotency/SQLite store
Nika's `runtime/idempotency.py` is strong, but Accessible Chess already has ACSDB schema/migration authority. Importing Nika's SQLite schema wholesale would create a second persistence authority. External-side-effect tools therefore remain fail-closed behind the `DurableEffectGuard` port until an Accessible Chess-owned integration is designed against the current storage model.

### Nika-Core ffmpeg extraction
The extractor depends on Nika process/file-promotion infrastructure. It also touches media/provider-compliance boundaries. Only the dependency-free WAV inspection was ported.

### Telegram-ChatGPT-Bridge process-shared flock write guard
`ops/runtime_write_reliability.py` uses Unix `fcntl/flock` and Telegram/server-specific write state. Accessible Chess is Windows-first, so this is not a safe direct transplant.

### Telegram request/rate middleware
`bridge/preparse_rate_guard.py` is WSGI/OpenAPI/Telegram-specific and would not improve the desktop product core.

### WordDeck release verifier
WordDeck contains strong package/NVDA qualification patterns, but current Accessible Chess `acs/version2_package_preflight.py` already implements more product-specific checksum, secret-leak, provenance and package gates. Copying WordDeck's verifier would duplicate authority.

### 12-6-ai. full checkpoint stack
Training-specific model/RNG/tensor/checkpoint logic is intentionally excluded from a chess desktop/media product.

### AudioTacticalFPS
The accessible owner-visible repository has no reusable implementation beyond coordination metadata on `main`; there is no code worth moving in this pass.

### scripture-archive
Current reusable candidates are domain/content-validation specific and do not improve the Media/Agent foundation enough to justify another authority.

## Tests

- `tests/test_crossrepo_agent_media_foundation.py`
- `tests/test_crossrepo_safety_reuse.py`

They cover retry safety, model privacy/fallback, tool risk boundaries, canonical fingerprints, checkpoints, WAV inspection, media reconciliation/timeline, budget accounting, accessibility text, privacy-safe errors, keyed concurrency, observation-vs-verification, and resource-ceiling narrowing.

## Public-repository confidentiality

The repository is public. This integration does not include the owner's confidential media-source/game-identification ranking or matching heuristic. Public code exposes generic evidence and reconciliation contracts only.
