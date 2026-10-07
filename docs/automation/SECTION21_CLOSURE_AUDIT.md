# Section 21 closure audit — Universal Chess Agent runtime and tool gateway

Canonical Section Plan revision:
`AHj4eMRgmsXXWqlCWeR_5F-46Ih3m_cfXBnu0AmnMUpGQPqYY1C4kuw6vk_it1ujhxcUx6rkI7tx6mcmEDrW7XxWNQQ2k4X3Ko91JiCnng`

Section:
`SECTION 21 — Universal Chess Agent runtime і tool gateway`

Owner directive:
On 2026-10-07 the repository owner explicitly directed autonomous completion and terminal closure of Section 21 in one run, with a durable GitHub DONE/closed marker and ordinary re-entry forbidden after closure.

## Canonical lineage and bounded convergence

Base Universal Agent intake:
- PR #2013
- branch `work/media-agent-crossrepo-intake-20261005`
- exact parent `6609c35ff5fa0b1f959806866ff7403e70efdbf3`

This finisher reuses, rather than replaces, the one existing Universal Agent authority. It converges only acceptance-critical child repairs:
- #2315 intake safety/public-error repair;
- #2161 bounded passive tool argument/result authority, including #2035 result safety;
- #2026 model-call cost/effect accounting repair;
- #2094 exact qualified local Ollama provider blob only (no subtitle/media feature intake).

Section 22 domain-tool expansion is intentionally excluded.

## Exact accepted source authorities on this finisher

- `acs/universal_chess_agent.py` — `be877a142dcb104abcf512a114dd78faca4df059`
- `acs/agent_tools.py` — `ff029facfb23340ffed18fbd4a0b0e55e1f5e719`
- `acs/agent_model_gateway.py` — `e9127b209ec8c1fb50dd4f916753763084d783f1`
- `acs/agent_model_contracts.py` — `088e759447c921dfeae2a40fe7af16275d7b3417`
- `acs/agent_checkpoint.py` — `e9cc46cf415c98f4ace5d307b80666d10e8e4ebb`
- `acs/agent_retry.py` — `1fd06a3d7425b97f2111b3d24d9c73e739526d67`
- `acs/agent_task_state.py` — `2e8e19d31c27ebc687baf0a01850f2471400ff12`
- `acs/agent_verification.py` — `1300eb8284692ef89bcda508d0aff579a45598cf`
- `acs/agent_budget.py` — `a4f50e7a929c7401fadbb0d46d831c7e3f0eb344`
- `acs/agent_resource_budget.py` — `ec501c7facf9723d8696b6cf88b9680e26c7f44d`
- `acs/agent_ollama_provider.py` — `cb2b66efe0b03e468a4339e0edb268d69e2d3596`
- `acs/chess_agent_tools.py` — `cf73c95d3f26c1ad4ae3ec255ef012ba52d35637`

Pinned canonical dependency interfaces consumed by this scope:
- `acs/board_service.py` — `5058733f0efe74bd42831b98c8f9cba83278d0cf`
- `acs/analysis_service.py` — `c5ca651a9ac299d3794278f9cfae8f16fcb938e4`

## Acceptance map

### 21.1 One Universal Chess Agent

PASS.

`UniversalChessAgentRuntime` is the single generic runtime authority. No second Agent runtime is introduced by this finisher. The architecture test rejects chess-rules/engine ownership inside generic Agent modules.

### 21.2 Typed tool registry/executor, durable jobs, Stop/cancel, bounded retries

PASS.

- `ToolSpec`, `ToolCall`, `ToolResult`, `ToolExecutor` form the typed fail-closed registry/executor.
- Arguments and results are detached, passive, JSON-safe and bounded by depth/item/text/serialized-size limits.
- High-impact/external effects require exact approval plus a durable `ToolEffectGuard` reserve/act/finalize boundary.
- `AgentCheckpoint`, effect-ledger fencing, `TaskState`, serializable `RetryIntent`, restart evaluation and bounded retry policy provide durable/restartable job-state semantics without creating a second scheduler.
- `UniversalChessAgentRuntime.cancel()` is the canonical run Stop/cancel boundary.
- Model calls, steps, response size, timeout, cost and child resource budgets are bounded.

### 21.3 ModelGateway/provider abstraction and local/remote routing

PASS.

`ModelGateway` owns provider registration/routing, privacy gating, safe fallback, typed errors and response identity validation. Provider kinds explicitly include `NO_LLM`, `LOCAL` and `CLOUD`.

The qualified local provider is the existing first-party `OllamaProvider`:
- endpoint default `http://localhost:11434/api/chat`;
- model default `qwen3:8b`;
- `stream=false`;
- `think=false`;
- loopback HTTP only;
- no cloud model names;
- no credentials embedded.

Remote providers remain replaceable `ModelProvider` implementations behind the same gateway; deterministic chess operation remains valid with no LLM configured.

### 21.4 No second chess/rules/orchestration authority

PASS.

Generic Agent runtime/gateway/tool/checkpoint/retry/verification modules do not import or implement chess rules, PGN/GameTree parsing or engine semantics. Chess-facing handlers delegate to Accessible Chess application services. `board_service.py` and `analysis_service.py` are pinned as consumed dependency interfaces.

### 21.5 Observe -> reason -> tool -> verify

PASS.

The runtime preserves exact user/model/tool turn order, permits only registered typed tools, feeds the bounded exact tool result into the next model turn, and separates observation from verification through `AgentObservation` / `AgentVerification`. Canonical tool handlers remain the authority for chess-state verification; model output never becomes chess truth by assertion.

## Existing exact-head evidence reused

- #2161 `Agent Tool Argument Authority` run `37528468027`: terminal SUCCESS on its exact candidate; this finisher reuses the exact qualified `agent_tools.py` result.
- #2035 `Agent Tool Result Authority` run `37528057708`: terminal SUCCESS; result hardening is inherited by #2161.
- #2094 `Media subtitle and Ollama reuse` run `37423994526`: terminal SUCCESS; this finisher reuses the exact qualified `agent_ollama_provider.py` blob only.
- #2315 previously executed its repaired formerly-red safety contracts successfully and then failed only because retained pytest-importing modules were invoked without installing pytest. That workflow defect was repaired on the same lineage by commit `0481fe17ff1032cbd1b1d5f62179c7829aa32c29`.
- #2026's prior RED exposed stale tests plus one old self-cancel expectation. Those test defects were repaired on the same lineage through `07f1bb8bbe537a84a59613504e96c334d2acdea4`; this Section-21 gate reruns the repaired budget/runtime tests on the converged candidate.

## Dependency treatment under the explicit owner-directed closure

Canonical plan dependencies are Sections 0, 12, 13 and 16.

- Section 0: already terminal DONE in the live closure registry.
- Section 16: already terminal DONE in the live closure registry.
- Sections 12 and 13 are **not** falsely declared DONE by this audit.

The owner's direct Section-21 closure instruction is treated as the same explicit out-of-order product decision already represented by terminal Section 9 in the live registry. Section 21 therefore closes against the exact immutable Board/Analysis service interfaces pinned above. Later Section-12/13 integration does not automatically reopen Section 21. Reopen is permitted only if that later integration demonstrably breaks a pinned Section-21 contract, consistent with Simplified Section Closure Protocol v3.

## Terminal-lock semantics after acceptance

After exact candidate qualification/integration/readback and durable registry update:
- `SECTION_21_STATE=DONE_TERMINAL`;
- ordinary workers MUST skip Section 21;
- no polishing, repeat audit, duplicate finisher or speculative hardening is allowed;
- reopen only for a concrete regression, invalid closure evidence, materially changed acceptance contract, or later integration demonstrably breaking this scope.

Manual NVDA/owner acceptance remains final whole-product work and is not an intermediate Section-21 blocker under Simplified Section Closure Protocol v3.
