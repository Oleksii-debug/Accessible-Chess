# Sequential Closure State

This file is the durable GitHub mirror for ordered Section/Subsection closure.

## Binding closure lifecycle v2

This registry obeys the root `AGENTS.md` **Terminal Section Closure Protocol v2**. The following invariants are mandatory when selecting or updating a front:

- **Closure is the optimization target.** Commit/PR count, execution-unit floors, depth targets and elapsed worker time do not justify additional mutation.
- **One mutation front.** Mutate only the earliest actionable unfinished Section, except for a minimal named direct dependency required to close it.
- **Audit existing first.** If acceptance-critical implementation already exists, qualify/close it instead of rebuilding or expanding it.
- **One canonical finisher.** Record/reuse one Section finisher lineage; intermediate feature/integration/prequal merges are not closure.
- **Candidate freeze.** Once internally controllable acceptance requirements are satisfied, designate and freeze an exact candidate SHA. No unrelated hardening or speculative edge-case work after freeze.
- **Exact-SHA qualification.** Pending CI freezes the candidate; it does not authorize a new SHA. A failed gate permits only the smallest proven gating repair before refreeze.
- **Integration then readback.** DONE requires required canonical integration plus post-merge/readback evidence, not merely an intermediate merge.
- **External-only remainder.** Use `INTERNAL_DONE_BLOCKED_EXTERNAL` when internal scope is exhausted and a genuinely external fact remains. This is not DONE, but the frozen Section becomes immutable for autonomous sequencing until the unblock condition changes.
- **No reconvergence carousel.** Do not repeatedly propagate a moving predecessor into later Sections. Later work waits for a frozen/accepted predecessor or the explicit external-block escape.
- **Acceptance boundary is fixed.** New non-gating improvements discovered after freeze go to later/backlog scope. They do not silently enlarge the current Section.
- **Reopen narrowly.** A DONE Section may reopen only for a demonstrated regression, invalid evidence, changed acceptance contract or breaking later integration; record the exact reason first.

Recommended lifecycle states are:
`OPEN -> IMPLEMENTING -> CANDIDATE_FROZEN -> QUALIFYING -> DONE`,
or `... -> INTERNAL_DONE_BLOCKED_EXTERNAL` when only an external unblock remains.
`REOPENED` is exceptional and must name the invalidated surface.

For the current front, durable state should identify: **canonical finisher**, **candidate SHA if frozen**, **remaining acceptance-critical gap**, and **exact unblock condition if externally blocked**.

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
| Section 0 | DONE | Canonical finisher PR #2346; accepted frozen source `dfdd077247e82e45596a044e5a606ec6c39ba17a`; exact pre-integration base `1bc2b88398d8ba76e43fd823e0693de99b7f06e1`; canonical integration merge `71a191075d489edb1dcddaae6801f2e8cff80050`. Focused run `37626867433`; Whole V3 run `37626867408`. | `dfdd077247e82e45596a044e5a606ec6c39ba17a` integrated by merge `71a191075d489edb1dcddaae6801f2e8cff80050` | Exact seven-path candidate qualified terminal SUCCESS on Ubuntu 22.04 + Windows 2025 in both focused and Whole V3 gates, including geometry/blob binding, compile, Section 0.1–0.5 executable contracts, retained format/source regressions and core chess selftest. Post-merge readback: integration branch head is `71a191075d489edb1dcddaae6801f2e8cff80050`; candidate -> merge is ahead by one merge commit with zero file delta, so accepted source bytes are preserved. |
| Section 1 | IMPLEMENTING — FRONT-1 | Canonical prepared finisher PR #2356 @ `b6eb5ca0f60dd9b4072c2dfc3676dbb86f18801b`; accepted Section-0 predecessor source is now `dfdd077247e82e45596a044e5a606ec6c39ba17a`. Dependency-safe child PR #2365 @ `5b8e3b32fad059569c92cd63a8765657929fb7f2` carries bounded FEN-publication counter preflight. | Not accepted | Section 0 dependency is closed. Resume Section 1 by one bounded history-preserving convergence onto accepted predecessor, consume unique child residuals, repin exact whole/source-corpus gates, then freeze/qualify one exact candidate. No predecessor carousel. |
| _Backfill only from exact current evidence; do not guess historical closure._ | OPEN | — | — | Add DONE rows only after exact current acceptance evidence exists. |
