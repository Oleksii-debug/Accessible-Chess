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
| Section 0 | CANDIDATE_FROZEN — QUALIFYING | Canonical finisher PR #2346; frozen exact candidate `dfdd077247e82e45596a044e5a606ec6c39ba17a`; exact base `1bc2b88398d8ba76e43fd823e0693de99b7f06e1`. Focused run `37626867433`; Whole V3 run `37626867408`. | Not accepted until terminal exact-SHA qualification and required integration/readback | Frozen geometry: ahead-only / behind=0 / exact merge-base / exactly seven paths. The latest mutation is the minimal repair of a proven exact-head retained-EPD-oracle gate failure; no further internally proven gating defect is known. Pending/queued CI does not authorize moving this SHA. |
| Section 1 | PAUSED — WAITING_ON_FROZEN_SECTION0 | Existing prepared PR #2356 @ `61549247033a8b65de10e09d2e4d52e4f978717d`; do not reconverge again while Section 0 candidate `dfdd077247e82e45596a044e5a606ec6c39ba17a` is qualifying. | Not accepted | Protocol v2 forbids a predecessor reconvergence carousel while the primary frozen candidate waits for CI. Resume Section 1 only after Section 0 terminal qualification/integration or a precisely recorded external-block escape. |
| _Backfill only from exact current evidence; do not guess historical closure._ | OPEN | — | — | Add DONE rows only after exact current acceptance evidence exists. |
