# AGENTS.md

## Terminal Section Closure Protocol v2 — owner directive 2026-10-07

**This section overrides every older coordination rule in this repository, including any instruction to use the full execution window, keep creating residual work, prepare FRONT-2, avoid idling, satisfy a depth/work-unit floor, or keep mutating while CI is pending. Product correctness/safety requirements remain binding.**

### Objective

Optimize for **honestly closed Sections**, not commits, PR count, execution units, branch activity, or the amount of hardening performed.

A worker must prefer the shortest evidence-correct path from the current repository state to terminal closure of the earliest actionable Section.

### Mandatory lifecycle

For the earliest actionable Section, execute this lifecycle in order:

1. **AUDIT EXISTING** — map the fixed acceptance contract to live code, tests, evidence, and already integrated capabilities. Existing correct implementation is an asset, not a reason to reimplement.
2. **IMPLEMENT ONLY MISSING** — change only acceptance-critical gaps. Reuse/repair/converge existing canonical work before creating anything new.
3. **CANDIDATE** — as soon as all internally controllable acceptance requirements appear satisfied, designate one canonical finisher lineage and one candidate SHA.
4. **FREEZE** — freeze that candidate. After freeze, unrelated hardening, polishing, speculative edge-case hunting, refactors, extra features, and “while we are here” changes are forbidden.
5. **QUALIFY EXACT SHA** — run the required tests/gates against that exact candidate. Pending/queued CI does not authorize changing the SHA.
6. **REPAIR ONLY PROVEN GATING FAILURE** — if qualification fails, make the smallest acceptance-relevant repair on the same canonical finisher, refreeze a new SHA, and rerun affected gates. A discovered non-gating improvement goes to backlog/later QA scope.
7. **INTEGRATE** — merge/converge the qualified candidate into the canonical integration authority required by the plan.
8. **POST-MERGE READBACK** — verify accepted tree/SHA and any required downstream evidence after integration.
9. **DONE** — update `SEQUENTIAL_CLOSURE_STATE.md` and applicable canonical control record in the same closure run, then immediately select the next Section.

### One-front law

- There is exactly **one mutation front**: the earliest actionable not-closed Section.
- Creating or mutating FRONT-2/Section N+1 is **forbidden** while Section N still has internally controllable acceptance work.
- Work on a later Section is allowed only when it is a **named direct dependency required to close the primary Section**, and only the minimum dependency slice may be changed.
- Do not create speculative prequalification, next-section integration, or reconvergence branches merely because the primary candidate is waiting for CI.
- Repeatedly propagating a moving Section-N parent into Section N+1 is forbidden. Section N+1 waits for a frozen/accepted predecessor, except for the explicit external-block rule below.

### External-block escape without false DONE

If all internally controllable acceptance work is complete and the only remaining requirements are genuinely external (for example human NVDA/physical-device evidence, vendor/certificate/account approval, externally unavailable infrastructure, or an external fact that cannot be manufactured):

- freeze the exact internal candidate;
- record **INTERNAL_DONE_BLOCKED_EXTERNAL** with exact SHA, completed evidence, missing external evidence, and the precise unblock condition;
- treat that Section as **immutable for autonomous sequencing** while the external condition is unchanged;
- move to the next earliest Section whose implementation does not depend on the missing external fact;
- do **not** call the blocked Section DONE;
- do **not** reopen or mutate it just to consume worker time;
- when the external fact arrives, requalify only the dependency surface it can invalidate, then complete terminal closure.

Queued CI is not automatically an external blocker. If the frozen exact-SHA CI is merely pending, keep the candidate frozen and check its result; do not move the SHA or invent new work. If CI is demonstrably unavailable for an extended period and no autonomous action can restore it, record the exact infrastructure blocker before using this escape.

### One canonical finisher

- Each active Section has one canonical finisher branch/PR/lineage, recorded in durable state.
- Before creating a branch or PR, inspect active lineages. Reuse the canonical finisher whenever possible.
- Parallel workers may contribute non-overlapping acceptance-critical fixes, tests, or evidence, but those contributions must converge into the same finisher.
- Alternate integration trees, competing “whole Section” PRs, and reconvergence carousels are forbidden.
- A merged PR into an intermediate feature/integration/prequal branch is **not Section closure**.
- If duplicate lineages already exist, preserve unique required changes, converge once, supersede the rest, and stop propagating duplicates.

### Acceptance-contract boundary

- The canonical Section plan defines the acceptance boundary. Workers may not silently enlarge it.
- After CANDIDATE/FREEZE, a newly imagined edge case does not block closure unless it demonstrates violation of an existing acceptance requirement, regression, security/correctness invariant, or required negative/recovery case.
- Non-gating improvements must be recorded for later scope instead of extending the current Section indefinitely.
- A work-unit/depth floor, token budget, run duration, “do not stop after one PR”, or “use the full execution window” rule can **never** force extra mutation after the closure candidate is ready.

### Already-implemented Section rule

If the Section’s required capability already exists in current canonical code:

- do not rebuild it;
- perform a closure audit against the acceptance contract;
- reuse current implementation/evidence;
- add only missing tests/evidence/integration;
- create/freeze the closure candidate;
- qualify and close it.

The correct action for an already-implemented Section is **qualification and closure**, not invention of more implementation.

### CI and SHA discipline

- One qualification cycle = one frozen SHA.
- Never invalidate green/pending exact-head evidence with unrelated commits.
- Never claim PASS from queued, cancelled, skipped, stale-base, different-SHA, or intermediate-branch CI.
- On failure, repair the proven failure only, then refreeze.
- On success, integrate promptly; do not continue polishing the candidate.

### Reopen discipline

A DONE Section may be REOPENED only for a concrete demonstrated reason: regression, invalid closure evidence, materially changed acceptance contract, or later integration that breaks the closed scope.

Before mutation, record the exact reopen reason and affected evidence. Reopen only the invalidated surface; do not restart the entire Section by default.

### Required worker decision at every run

Before writing code, answer from live state:

1. What is the earliest actionable Section?
2. Does its required implementation already exist?
3. What exact acceptance-critical gap remains?
4. What is the one canonical finisher?
5. Is there already a frozen candidate SHA?
6. If frozen, am I permitted to mutate it? Only a proven gating failure permits that.
7. Can this run close the Section now? If yes, closure takes priority over every depth/work-unit target.

**Closure beats activity. Frozen candidates beat moving targets. Existing implementation beats reimplementation. Exact evidence beats PR count.**


## Canonical autonomous worker policy

Objective: move Accessible-Chess toward a complete, working, verified product as quickly as possible.

This root file is the highest-priority repository instruction for autonomous worker coordination. It supersedes any older repository text that imposes fixed worker counts, coordinator counts, WIP caps, serial-only lanes, mandatory ownership/claim locks, exclusive integration owners, mandatory waiting for another PR, or "stop because CI is queued" behavior. Older documents remain historical/technical context only where they conflict with this section.

### Parallelism and autonomy

- There is no repository-defined maximum number of autonomous workers.
- There is no repository-defined maximum number of simultaneous work packages or pull requests.
- Ownership, claims, leases, assignments, queues, and coordinator labels are advisory coordination metadata only. They must not prevent useful safe work.
- A worker may create branches, commits, pull requests, comments, tests, fixes, integration commits, and merges when repository and GitHub permissions allow it and the change is honestly verified.
- A worker does not need to wait for a designated human or designated integration worker merely because an older document says so.
- Dependency or merge order constrains final integration order only. It must not stop independent implementation, testing, research, hardening, documentation, fixtures, adapters, accessibility work, packaging work, or other non-conflicting work.
- A queued, pending, slow, or unavailable CI run is never by itself a reason to terminate the worker. Record the pending qualification state and immediately continue with another valuable independent task.
- A blocked first workline is never by itself a reason to terminate the worker. Preserve the blocker and continue with the next useful unblocked workline.
- STATUS: BLOCKED is allowed only when the worker has exhausted all reasonably available safe independent work that can materially advance the product in the current run.
- Do not idle merely because another pull request, branch, worker, check, or review is active.
- If another worker is touching the same area, prefer a non-conflicting task; if overlap is unavoidable, reconcile/rebase rather than abandoning the run.
- Do not artificially keep main/PR throughput low for coordination convenience. Optimize for real completed product progress.

### What this policy does not remove

This policy removes worker-orchestration throttles, not product correctness requirements. It does not authorize weakening security, data integrity, financial/risk invariants, accessibility, licensing, privacy, test truth, release evidence, or other domain-specific safety/correctness requirements. Do not bypass externally enforced GitHub permissions or branch-protection rules; instead continue useful work elsewhere while they are pending.

### Durable state

Chat history is temporary working memory. Preserve meaningful implementation state in the repository through code, commits, branches, pull requests, issues/comments, tests, and existing canonical project records. Do not leave important progress only in chat.

### Completion behavior

Use the full execution window for real progress. Do not stop after the first commit, PR, green test, queued check, review request, or blocker while useful safe work remains.
