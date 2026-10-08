# Accessible Chess — Sections 49/50 acceptance and live-evidence ledger (2026-10-08)

Canonical acceptance contract: https://docs.google.com/document/d/1ITsUBFwwETRICctcOWLd6atuMcCFZg6v5-wVFumIyxE/edit — clauses 49.1–49.6 and 50.1–50.6.

**CURRENT STATE: BOTH OPEN / NOT DONE.** Offline fixtures do not equal real authenticated API responses, video frame analysis, YouTube playback or full-product integration.

## Reuse and source truth

- Existing authority: acs/agent_model_gateway.py, acs/agent_model_contracts.py, acs/universal_chess_agent.py. No router or chess rules authority #2.
- Existing video/board: acs/media_foundation.py, acs/media_application.py and acs/local_video_library.py. No duplicate FEN recognizer.
- Parent source: feature/sections43-50-full-product-20261008-sol56 at 89afa3c9af3dd4620bd6b7bcf07bb0912a2a4585.
- Active incremental implementation PR: https://github.com/Oleksii-debug/Accessible-Chess/pull/2501.

## Section 49 — clauses

- 49.1: Private Drive Providers directory and Mistral/Groq/Gemini/OpenRouter/NVIDIA/DeepSeek/Cohere account metadata folders discovered, no re-registration. Keys deliberately not copied or disclosed.
- 49.2: Mistral-first fixed-origin HTTPS /models and /chat/completions connector with env-only MISTRAL_API_KEY and secret-safe response reporting. LIVE credential validation **NOT DONE**.
- 49.3: Added Groq, Gemini OpenAI compatibility, Cohere compatibility, OpenRouter, DeepSeek, NVIDIA NIM under same ModelGateway. >=3 independent real responses **NOT DONE**.
- 49.4: Fixed HTTPS hosts, disabled redirects and environment proxy trust, bounded text/output, no implicit payment or signup, explicit privacy permission; secure Drive-to-runtime secret delivery and account quota receipts **NOT DONE**.
- 49.5: Offline adversarial tests: authenticated-shape mock, 401, 429, timeout, malformed identity/JSON, 1MB bound, privacy denial, no-effect preflight fallback. Actual real PGN/FEN/context response comparison **NOT DONE**.
- 49.6: Canonical chess tools and Universal Chess Agent reused. Final accessible provider switch, multi-model comparisons, text/vision/audio capability reporting, Stockfish integration and keyboard UI **NOT DONE**.

## Section 50 — clauses

- 50.1: lawful MP4/WebM metadata/catalog is existing, and optional real local video byte SHA is supported. Full decoded frames/timecodes -> verified canonical FEN -> Stockfish -> Books/Library -> AI Agent -> resume is **NOT DONE**.
- 50.2: Real YouTube embed seek/pause/sync/unavailable browser checks **NOT DONE**.
- 50.3: Mistral-first authenticated live test runner with explicit operator no-cost authorization written; real Mistral plus 2 independent provider responses **NOT DONE**.
- 50.4: Offline provider failure tests implemented. Real bad video/incorrect orientation/variation/restart/fallback/previous-move integration **NOT DONE**.
- 50.5: section49-50-evidence-v1 typed JSON reports source SHA, provider/model, model listing auth, latency, tokens, errors, and distinct evidence classes LIVE_MODEL/OFFLINE_VIDEO/YOUTUBE_EMBED. Real sanitized per-endpoint GitHub reports **NOT DONE**.
- 50.6: Owner-ready lawful real video, populated working test library, provider settings and Section 52–53 handoff **NOT DONE**.

## Exact code and safety evidence

- acs/agent_cloud_provider.py — restricted cloud inference adapter, no embedded keys; requests cannot mutate chess state.
- tests/test_section49_cloud_provider.py — simulated HTTP negative/positive provider contracts.
- tools/section49_50_live_qualification.py — opt-in private evidence collector, not a live PASS generator.
- tests/test_section49_50_evidence.py — prevents mock or video-byte evidence from being promoted to semantic or LIVE PASS.
- .github/workflows/section49-cloud-provider-qualification.yml — Ubuntu22.04/Windows2025 exact-PR-head Python 3.12 test jobs, pinned httpx.

## Qualification rule

Source/mock/real LIVE model/video hashes/browser YouTube/full E2E are different evidence classes. Never make an unauthorized call or assume free-tier quotas. Never publish secrets or the owner-provided private files. Pending/queued/failed CI is not SUCCESS. No terminal DONE until exact integration, executed admissible tests and postmerge readback. Current PR is work in progress, not final integration.

## Further incremental qualification added in this same PR

- `acs/universal_chess_agent.py`: an explicit bounded fallback list flows through the original `ModelGateway`; the Agent does not start a second router. On UNKNOWN-effect errors, the existing `ModelCostBudget` conservatively keeps estimated-unbilled cost instead of releasing an uncertain reservation. NO_EFFECT releases it.
- `tests/test_section49_agent_fallback.py`: actual existing Universal Agent + Gateway seam using typed fake providers, including NO_EFFECT fallback, UNKNOWN-effect no-duplicate, privacy preflight, budget, invalid routes.
- `tests/test_section49_agent_cloud_tool_roundtrip.py`: actual existing Agent, registered read-only board FEN tool, two turn HTTP mock loop, and malicious unregistered tool request proving no board mutation.
- `tests/test_section50_media_agent_integration.py`: mocked HTTP + existing Media Core, explicit chess ref restore, real canonical Board rules and state roundtrip; no arbitrary model request can advance board state.
- `tests/test_section50_youtube_boundary.py`: simulated YouTube URL -> player status -> seek/pause/unconfirmed restore refusal, source mismatch and malformed URLs. This is explicitly a **mocked browser-player contract**, not a real YouTube playback PASS.
- `tools/section50_real_video_source.py`, `.github/workflows/section50-real-video-source.yml`: actual Ubuntu runner attempt to download CC0 chess WebM from existing source catalog, bound SHA-256 verify, invoke FFprobe and FFmpeg for a real frame hash, and persist a metadata-only artifact. The result remains `SOURCE_FRAME_DECODED_SHA_NOT_YET_PINNED` until independently reviewed/expected SHA pinned; no semantic/FEN PASS.
- Dual-OS workflow `.github/workflows/section49-cloud-provider-qualification.yml` executes relevant Section 49/50 offline suites. CI run state must be checked for the latest **exact SHA**, not a prior green attempt.

Both Sections **49/50 remain OPEN** until authenticated provider test receipts, external video and YouTube playback semantic qualification, physical keyboard/NVDA product release, post-integration readback, and all clause 49.1–49.6 / 50.1–50.6 criteria have independently passed.
