# Section 23 closure audit — AI Coach, review, research and training

Canonical plan: **Section 23 — AI Coach, game review, research і training workflows**.

## Accepted implementation

Canonical finisher PR: **#2434**.

Exact accepted candidate:

`fadf12059b941c61459870938027833fe51f21e1`

Integrated Agent authority:

`59eedf4e33de0565d0ad47d11206b6743dd3bff8`

The candidate was built directly on terminal Section-22 Agent integration
`92b9b6af16977c301e1a5c69b908bc7aa478262a`.

## Scope

- **23.1** Evidence-first position/move explanation collects canonical
  `board.current` plus bounded `engine.analyze` evidence before model prose.
- **23.2** Game review collects canonical `gametree.current`, Stockfish evidence
  and bounded related Library results; model instructions forbid claiming
  opening/endgame facts absent from evidence.
- **23.3** Training mode creates a non-persistent exercise / Guess-the-Move /
  adaptive-training prompt from canonical Board, Stockfish and
  `training.status` evidence. It does not create a second Training store.
- **23.4** Media mode grounds answers in `media.status`, canonical Board and
  Stockfish. Local `media.seek` / `media.restore_position` are denied by
  default and are exposed only by an explicit per-run owner allowlist.
- **23.5** Classroom Teacher Assistant is deliberately excluded; it remains
  Section 36 exactly as required by the plan.

## Authority invariants

- one existing `UniversalChessAgentRuntime`;
- one existing `ToolExecutor`;
- no second chess rules, engine, GameTree, Library, Training or Media authority;
- required grounding tool failure stops the workflow before the model call;
- read-only evidence tools are verified as `READ_ONLY`;
- ordinary Coach runs receive an empty model tool allowlist;
- Media writes require exact per-run authorization and stay behind the existing
  canonical Media tool boundary.

## Dependency evidence

Section-22 closure audit records Sections 6, 13, 20, 21 and 22 as terminally
closed before this candidate. Section 23 therefore has no unresolved hard plan
dependency at terminal integration.

## Qualification and readback

Dedicated workflow:
`.github/workflows/sections23-24-agent-closure.yml`.

Exact-head run **37684869279** registered Ubuntu 22.04 and Windows 2025 jobs.
At integration both jobs remained queued/unstarted; this is **not GREEN** and
not an executed failure. Simplified Section Closure Protocol v3 treats hosted
runner unavailability as external when repository-controllable work is
complete and no executed RED exists.

Post-merge candidate -> merge compare is ahead by one / behind zero with exact
merge-base at the candidate and **zero file delta**. Readback is byte-identical
for `agent_coach.py`, `agent_reliability.py`, `agent_voice.py`,
`universal_chess_agent.py`, the closure regression and workflow.

## Terminal lock

`SECTION_23_STATE=DONE_TERMINAL`

Ordinary workers must not re-enter, reimplement, polish or repeat-audit Section
23. Reopen only for a concrete demonstrated regression, invalid closure
evidence, materially changed acceptance contract, or a later integration that
demonstrably breaks this closed scope.
