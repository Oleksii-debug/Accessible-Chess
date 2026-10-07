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
| Section 0 | OPEN — INTERNALLY_ADVANCED / BLOCKED_EXTERNAL_CI | Canonical PR #2346 @ `dfdd077247e82e45596a044e5a606ec6c39ba17a`; exact predecessor/base `1bc2b88398d8ba76e43fd823e0693de99b7f06e1`. Focused run `37626867433`; Whole V3 run `37626867408`. | Not accepted; exact-head candidate only | Geometry remains ahead-only / behind=0 / exact merge-base / exactly six paths. Same-lineage hardening now includes passive bounded diagnostics, serialized routing authority, process-control and cooperative-Cancel mutation precedence, and host-owned accepted ImportReport snapshots that detach adapter-retained mutable aliases. Required exact-head qualification is QUEUED/QUEUED; nonterminal is not PASS. |
| Section 1 | OPEN — DEPENDENCY_SAFE_PREPARED / BLOCKED_ON_SECTION0_RECONVERGENCE_AND_CI | Canonical prepared PR #2356 @ `a959ea2607ba3aafe1a79877ffd9a0a9c82057aa`; base branch is canonical #2346 lineage. Source/corpus run `37626845528`; Whole run `37626845474`. | Not accepted; prepared candidate only | Current prepared lineage has FEN/SAN/Position work and predecessor-aware qualification, but canonical Section 0 advanced again to `dfdd077247e82e45596a044e5a606ec6c39ba17a`; Section 1 must history-preservingly reconverge and repin to that exact predecessor before qualification can count. Existing active reconvergence claim should be converged, not duplicated. Section 1 cannot close before honest Section-0 acceptance and its own terminal exact-head qualification. |
| _Backfill only from exact current evidence; do not guess historical closure._ | OPEN | — | — | Add DONE rows only after exact current acceptance evidence exists. |
