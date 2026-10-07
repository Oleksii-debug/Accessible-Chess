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
| Section 1 | CANDIDATE_FROZEN — QUALIFYING | Canonical finisher PR #2356; frozen exact candidate `fce5c75c65cf9abd3d134086279f20a6f5d63ef1`; accepted Section-0 predecessor `dfdd077247e82e45596a044e5a606ec6c39ba17a`. Proven gate repairs consumed: lawful-corpus canonical-legality curation; Version-2 `position.copy_fen` projection; editable PositionState representation vs strict playable `Board.fen()` publication. Fresh exact source/corpus run `37634398144`; fresh exact Whole run `37634398166`. | Not accepted until both required exact-SHA gate families are terminal SUCCESS, followed by canonical integration and post-merge readback. | Exact predecessor-relative geometry remains 48 paths, ahead-only / behind=0 / exact merge-base. Current evidence: `acs/webapp.py=18e41885299bc05e03d8a3419bbad838fc2bfd68`; `tests/test_fen_position_editor_complete_user_flow.py=77e6b6a3925d3af9fb065862acb6435826afef6e`; `acs/version2_profile.py=87ed363d64e8c3d6de291dd63376a42e059b0a29`; source workflow `6757c3a064d696804285a37a083a1ec66994c2bb`; Whole workflow `c694848e4cc18004fd13e764a487c63dd118c23d`; closure receipt `4a87c06fda560828e4eab0e6adc160a76ea46acd`. Source bindings 11/11 and Whole bindings 47/47 were independently read back with zero mismatch. Candidate remains frozen while these exact-SHA runs are pending; only a newly proven gating failure may authorize another successor. |
| _Backfill only from exact current evidence; do not guess historical closure._ | OPEN | — | — | Add DONE rows only after exact current acceptance evidence exists. |
