# Sequential Closure State

This file is the durable GitHub mirror for ordered Section/Subsection closure.

## Binding worker policy

This registry follows the **current root `AGENTS.md`**. Its
**Simplified Section Closure Protocol v3** is live and binding. It overrides Terminal
Section Closure Protocol v2 and every older conflicting Section-closure rule.

Current durable-state interpretation:
- the canonical Section plan determines ordered product scope and DONE truth;
- there is one mutation front: the earliest actionable unfinished Section;
- a frozen candidate SHA is immutable unless available qualification proves a concrete acceptance-gating failure;
- all repository-controllable work must be complete and all tests/checks actually available to autonomous workers must pass;
- manual owner/NVDA/device acceptance is final whole-product work and does not block intermediate Sections;
- externally unavailable or stuck hosted CI does not permanently block an otherwise complete intermediate Section when the available exact-SHA repository evidence is sufficient and no known failing acceptance check remains;
- canonical integration and post-integration readback remain required before DONE;
- parallel workers must converge acceptance-critical work into one canonical finisher;
- preserve meaningful implementation and blocker state outside chat in repository code, tests, PRs/comments and this registry.

Recommended state labels:
`OPEN`, `IMPLEMENTING`, `CANDIDATE_FROZEN`, `QUALIFYING`,
`INTERNAL_DONE_BLOCKED_EXTERNAL`, `DONE`, and exceptional `REOPENED`.

## Rules

- Read the current canonical Section plan and live default branch before updating this file.
- Record only evidence-backed DONE state; never infer closure from a chat summary, a PR existing, or unrelated/stale CI.
- Once recorded DONE, a Section/Subsection is skipped by normal workers and is not re-entered unless it is explicitly marked REOPENED for a demonstrated regression, invalidated closure evidence, changed acceptance contract, or broken later integration.
- If parallel workers produce duplicate closure lineages, preserve one canonical lineage, converge unique required changes, then close/supersede the duplicate and delete the duplicate branch when safe.
- Update this ledger in the same run that closes or reopens scope.
- DONE rows must name exact accepted source/build evidence.

## Closure registry

| Section / Subsection | State | Canonical evidence / lineage | Accepted source / build | Notes |
| --- | --- | --- | --- | --- |
| Section 0 | DONE | Canonical finisher PR #2346; frozen accepted candidate `dfdd077247e82e45596a044e5a606ec6c39ba17a`; focused run `37626867433` SUCCESS on Ubuntu + Windows; Whole V3 run `37626867408` SUCCESS on Ubuntu + Windows; integrated by merge commit `71a191075d489edb1dcddaae6801f2e8cff80050` into `converge/section0-whole-contract-v2-20261007-s56`. | Accepted source candidate `dfdd077247e82e45596a044e5a606ec6c39ba17a`; post-merge branch head `71a191075d489edb1dcddaae6801f2e8cff80050`. | Post-merge readback proves the accepted candidate is the exact merge-base/second parent and the merge commit is ahead by one with **zero file delta** from the qualified candidate. Canonical Section plan still names Section 0 first; no human/NVDA claim is required for this data-contract closure. |
| Section 1 | DONE | Canonical finisher PR #2356; frozen candidate `cc379e0de20512303e6dbcbd9c6d135cf59d4363`; Whole Contract run `37643418018` terminal SUCCESS for Ubuntu, Windows and lawful-fen-corpus; Source Snapshot run `37643417215` terminal SUCCESS for Ubuntu + Windows source-boundary. Integrated by merge commit `d38cdf52f38fdd4741fb086e51e163e403b645d5`. | Accepted source candidate `cc379e0de20512303e6dbcbd9c6d135cf59d4363`; post-merge head `d38cdf52f38fdd4741fb086e51e163e403b645d5`. | The remaining duplicate lawful-corpus job in Source Snapshot stayed externally nonterminal while the same exact candidate already had a terminal successful lawful-fen-corpus in Whole Contract and both source-boundary platform jobs were successful. Under Simplified Closure Protocol v3 this external runner state does not keep the intermediate Section open. Post-merge compare is ahead by one, behind zero, with **zero file delta** from the accepted candidate. |
| Section 16 | DONE — TERMINAL | Canonical Section plan revision `AHj4eMRgmsXXWqlCWeR_5F-46Ih3m_cfXBnu0AmnMUpGQPqYY1C4kuw6vk_it1ujhxcUx6rkI7tx6mcmEDrW7XxWNQQ2k4X3Ko91JiCnng`; canonical finisher PR #2003; frozen accepted candidate `7bf0a28dc65d5ceef45f78af0a5f023503b79a28`; Canonical Media Core Foundation run `37530932640` SUCCESS; Architecture Dynamic Import Boundary run `37530932826` SUCCESS on Ubuntu 22.04 + Windows 2025; integrated by merge commit `ad148043cc4b03dac093cddf8e9aa04df6285b0d` into `converge/current-product-books-provider-20261005-ooxple7`. | Accepted source candidate `7bf0a28dc65d5ceef45f78af0a5f023503b79a28`; post-merge head `ad148043cc4b03dac093cddf8e9aa04df6285b0d`. | Sections 16.1–16.5 are complete: provider-neutral MediaSession/deterministic MediaClock; immutable typed MediaEvidence; fail-closed ChessStateReconciler delegating to canonical chess authority; MediaPositionTimeline timestamp-to-position mapping; separate media/analysis cursors with restart/resume and cache invalidation. Post-merge compare is ahead by one, behind zero, with **zero file delta** from the exact qualified candidate. Intermediate human/NVDA acceptance is not required by Simplified Closure Protocol v3. Ordinary workers MUST skip this Section; reopen only for a demonstrated regression, invalid closure evidence, materially changed acceptance contract, or later integration that demonstrably breaks this scope. |
| Section 18 | DONE | Canonical finisher PR #2012; frozen accepted candidate `9939e3733adc1c00999d1a94adff5853900c9cc5`; Structured Broadcast Canonical Boundary run `37531146720` terminal SUCCESS on Ubuntu 22.04 and Windows 2025; Media Core dependency head `7bf0a28dc65d5ceef45f78af0a5f023503b79a28` had Canonical Media Core Foundation run `37530932640` SUCCESS and Architecture Dynamic Import Boundary run `37530932826` SUCCESS. Integrated by merge commit `550b2a281466a008f352093e6ba03b24160784e0` into `work/accessible-chess-20261005-media-core-sol56n4q8`. | Accepted Section 18 candidate `9939e3733adc1c00999d1a94adff5853900c9cc5`; post-merge branch head `550b2a281466a008f352093e6ba03b24160784e0`. | Canonical plan scope 18.1–18.5 is satisfied by provider-neutral `StructuredBroadcastProvider`, replaceable Lichess adapter, canonical PGN/GameTree/legality application binding, delay/reconnect/stale/disconnected/ambiguous handling, and accessible current/previous/next live-position navigation. Post-merge compare is ahead by one, behind zero, with **zero file delta** from the qualified candidate. **TERMINAL LOCK:** ordinary workers MUST NOT re-enter Section 18 unless a concrete regression, invalid closure evidence, materially changed acceptance contract, or later integration break is first recorded as `REOPENED`. Manual owner/NVDA acceptance remains final whole-product work under Simplified Section Closure Protocol v3. |
| _Backfill only from exact current evidence; do not guess historical closure._ | OPEN | — | — | Add DONE rows only after exact current acceptance evidence exists. |
