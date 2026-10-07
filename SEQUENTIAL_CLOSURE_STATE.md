# Sequential Closure State

This file is the durable GitHub mirror for ordered Section/Subsection closure.

## Binding worker policy

This registry follows the **current root `AGENTS.md`**. Its
**Terminal Section Closure Protocol v2** is live and binding. It overrides older
coordination text that would force extra mutation, FRONT-2 preparation, depth/work-unit
floors, residual hunting, or candidate movement while exact-SHA qualification is pending.

Current durable-state interpretation:
- the canonical Section plan determines ordered product scope and DONE truth;
- there is one mutation front: the earliest actionable unfinished Section;
- a frozen candidate SHA is immutable unless its required exact-SHA qualification proves
  a concrete acceptance-gating failure;
- queued/pending CI is not PASS and does not authorize candidate mutation;
- exact-SHA qualification, canonical integration and post-integration readback remain
  evidence requirements where the Section contract requires them;
- parallel workers must converge acceptance-critical work into one canonical finisher;
- external blockers never justify false DONE;
- preserve meaningful implementation and blocker state outside chat in repository code,
  tests, PRs/comments and this registry.

Recommended state labels:
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
| Section 1 | CANDIDATE_FROZEN — QUALIFYING | Canonical finisher PR #2356; frozen exact candidate `c3e05acf8c8dbcaa694665e94255bef5390d0726`; accepted Section-0 predecessor `dfdd077247e82e45596a044e5a606ec6c39ba17a`. Proven bounded repairs: editor representation boundary (`37633066532`), strict-FEN king-capture fixture alignment (`37633066960`), adjacent-kings activation-oracle correction (`37634398144`, Windows job `112837126679`), and historical king-gate authority hygiene. | Not accepted until exact-SHA source/corpus run `37635721281` and Whole run `37635721041` are terminal SUCCESS, followed by canonical integration and post-merge readback. | Product repair apex is `fce5c75c65cf9abd3d134086279f20a6f5d63ef1`; later commits are test/evidence/authority convergence only. Current lineage preserves strict `Board.fen()` gameplay publication, canonical `PositionState` editor representation, canonical Board/SAN legality, immutable historical child-gate authority, and 48-path accepted-predecessor geometry. Queued/pending/cancelled/stale runs are not PASS and do not authorize mutation. |
| _Backfill only from exact current evidence; do not guess historical closure._ | OPEN | — | — | Add DONE rows only after exact current acceptance evidence exists. |
