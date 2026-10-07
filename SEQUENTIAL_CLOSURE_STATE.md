# Sequential Closure State

This file is the durable GitHub mirror for ordered Section/Subsection closure.

## Binding worker policy

This registry follows the **current root `AGENTS.md`**. The former repository-level
Terminal Section Closure Protocol v2 was removed from the live root policy and must
not be treated here as a higher-priority orchestration rule.

Current durable-state interpretation:
- the canonical Section plan still determines ordered product scope and DONE truth;
- exact-SHA qualification and post-integration readback remain evidence requirements
  whenever a Section's acceptance contract uses them;
- queued/pending CI is not PASS, but it is also not a reason for an autonomous worker
  to terminate or idle when safe, useful, non-conflicting work remains;
- parallel claims/leases are advisory; prefer disjoint work and reconcile real overlap;
- never weaken correctness, integrity, accessibility, licensing, privacy, release,
  or test truth merely to increase throughput;
- preserve meaningful implementation and blocker state outside chat in repository
  code, tests, PRs/comments and this registry.

Recommended state labels remain descriptive rather than orchestration locks:
`OPEN`, `IMPLEMENTING`, `CANDIDATE_FROZEN`, `QUALIFYING`,
`INTERNAL_DONE_BLOCKED_EXTERNAL`, `DONE`, and exceptional `REOPENED`.

## Rules

- Read the current canonical Section plan and live default branch before updating this file.
- Record only evidence-backed DONE state; never infer closure from a chat summary, a PR existing, queued CI, or a single green test.
- Once recorded DONE, a Section/Subsection is skipped by normal workers and is not re-entered unless it is explicitly marked REOPENED for a demonstrated regression, invalidated closure evidence, changed acceptance contract, or broken later integration.
- If parallel workers produce duplicate closure lineages, preserve one canonical lineage, converge unique required changes, then close/supersede the duplicate and delete the duplicate branch when safe.
- Update this ledger in the same run that closes or reopens scope.
- For rapidly moving OPEN canonical PRs, store the canonical PR/ref and blocker as durable authority; any observed SHA/run is informational only until re-late-bound. DONE rows must name exact accepted source/build evidence.

## Closure registry

| Section / Subsection | State | Canonical evidence / lineage | Accepted source / build | Notes |
| --- | --- | --- | --- | --- |
| Section 0 | DONE | Canonical finisher PR #2346; frozen accepted candidate `dfdd077247e82e45596a044e5a606ec6c39ba17a`; focused run `37626867433` SUCCESS on Ubuntu + Windows; Whole V3 run `37626867408` SUCCESS on Ubuntu + Windows; integrated by merge commit `71a191075d489edb1dcddaae6801f2e8cff80050` into `converge/section0-whole-contract-v2-20261007-s56`. | Accepted source candidate `dfdd077247e82e45596a044e5a606ec6c39ba17a`; post-merge branch head `71a191075d489edb1dcddaae6801f2e8cff80050`. | Post-merge readback proves the accepted candidate is the exact merge-base/second parent and the merge commit is ahead by one with **zero file delta** from the qualified candidate. Canonical Section plan revision `AHj4eMRgmsXXWqlCWeR_5F-46Ih3m_cfXBnu0AmnMUpGQPqYY1C4kuw6vk_it1ujhxcUx6rkI7tx6mcmEDrW7XxWNQQ2k4X3Ko91JiCnng` still names Section 0 first; no human/NVDA claim is required for this data-contract closure. |
| Section 1 | CANDIDATE_FROZEN — QUALIFYING | Canonical finisher PR #2356; refrozen exact candidate `1f3a60ba27f144c8b44ce11827e68dbd16f833e6`; accepted Section-0 predecessor `dfdd077247e82e45596a044e5a606ec6c39ba17a`; dependency child #2365 and proven gate-repair child #2367 are consumed. Source/corpus run `37629876577`; Whole run `37629876837`. | Not accepted until terminal exact-SHA qualification plus required integration/readback | Prior 45-path candidate `45192b7e79b7c262fcff2c6164fc273610d25922` was superseded only after its lawful-corpus gate had already proven an acceptance failure: strict PGN parsing admitted game 9 with `Rd1d2`, while canonical GameTree legality rejected it. #2367 now filters curation through `acs.gametree_legality.validate_game_legality` without expanding SAN/Board authority. Exact predecessor-relative geometry is 47 paths, behind=0, exact merge-base. Source workflow `9fc6b77578ac211182a5a1ccbc720e990c0e99a3`, Whole workflow `62800ab6bbf2be90193341a78d58c5423fe70bf2`, lawful builder `1137eac8804bbef600921853c37a69a77588f03c`, builder regression `b564cc35d7c336559370ed43b05d58d9b1a4e8b0`, and closure receipt `712e6d0e44cfad1fffbed0b5096be9c9d121f634` are exact-bound. Runs are currently queued; queued is not PASS. |
| _Backfill only from exact current evidence; do not guess historical closure._ | OPEN | — | — | Add DONE rows only after exact current acceptance evidence exists. |
