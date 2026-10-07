# AGENTS.md

## Canonical autonomous worker policy

Objective: move Accessible-Chess toward a complete, working, verified product as quickly as possible.

This root file is the highest-priority repository instruction for autonomous worker coordination. It supersedes any older repository text that imposes fixed worker counts, coordinator counts, WIP caps, serial-only lanes, mandatory ownership/claim locks, exclusive integration owners, mandatory waiting for another PR, or "stop because CI is queued" behavior. Older documents remain historical/technical context only where they conflict with this section.

### Parallelism and autonomy

- There is no repository-defined maximum number of autonomous workers.
- There is no repository-defined maximum number of simultaneous work packages or pull requests.
- Ownership, claims, leases, assignments, queues, and coordinator labels are advisory coordination metadata only. They must not prevent useful safe work.
- A worker may create branches, commits, pull requests, comments, tests, fixes, integration commits, and merges when repository and GitHub permissions allow it and the change is honestly verified.
- A worker does not need to wait for a designated human or designated integration worker merely because an older document says so.
- Parallel implementation, testing, research, hardening, documentation, fixtures, adapters, accessibility and packaging are allowed only when consistent with the ordered Sequential closure authority below: prioritize the earliest unfinished Section and use later work only when dependency-safe or directly supportive.
- A queued, pending, slow, or unavailable CI run is never by itself a reason to terminate the worker. Record the pending qualification state and continue only work permitted by the current ordered closure front.
- A blocked primary closure front may be left only after all safe internally controllable residual work is exhausted and the blocker is durably recorded; later work must remain dependency-safe.
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

### Active required product lanes — owner directive 2026-10-05

All autonomous workers must also read:

- `docs/CANONICAL_PRODUCT_VISION_AMENDMENT_2026-10-05.md`
- `docs/MEDIA_INTELLIGENCE_AND_CHESS_AGENT_ARCHITECTURE.md`

The following are **active required product scope now**, not distant backlog:

- Formats / Library / ChessBase correctness and real-corpus qualification;
- Media Intelligence for live and recorded chess, including synchronized canonical board state;
- the Universal Chess Agent over typed Accessible Chess application tools;
- simplified Classroom/teaching core where it delivers concrete value.

These remain required product scope, but they are subordinate to the Sequential closure authority below. They do not authorize skipping the earliest unfinished Section. If work on the primary front is complete or genuinely non-actionable, refresh live state and take only dependency-safe work consistent with the ordered frontier.

Any older repository text that says the AI Coach/Agent or media intelligence must not be implemented yet is superseded by the 2026-10-05 owner amendment.

The repository is currently public. Do not publish proprietary/private source-discovery, game-identification, ranking or synchronization heuristics merely to document implementation. Public code/docs should expose stable interfaces, correctness rules, tests and provider-compliance boundaries. Private commercial strategy remains in the owner's private project records.

## Sequential closure authority — owner directive 2026-10-07

This section is the controlling coordination rule if any older repository text, worker prompt, issue, roadmap note, swarm rule, claim/ownership rule, or “parallel lane” instruction conflicts with it.

- Read the current canonical ordered Section plan and the live repository state before choosing work.
- The numerically earliest Section that is not honestly closed is the primary closure front. The next unfinished Section may be prepared only when this is dependency-safe, directly removes a dependency, or the primary front is genuinely non-actionable after all safe internal residual work is exhausted.
- Parallel workers are allowed, but parallelism does not authorize skipping the ordered closure front. Workers should take non-overlapping residuals of the same current front or dependency-safe preparation for the next front.
- A Section or Subsection may be marked DONE only after its required implementation/integration and applicable tests, negative/failure/recovery evidence, accessibility/security/performance/packaging evidence, and exact durable source state are satisfied.
- Every DONE Section/Subsection must be recorded durably in GitHub before the worker moves on. Use `SEQUENTIAL_CLOSURE_STATE.md` plus the repository’s existing canonical issue/status/control records when applicable.
- Once a Section/Subsection is durably recorded DONE, workers MUST NOT routinely re-enter it for reimplementation, polishing, re-auditing, or repeat verification. Skip it and work on the earliest unfinished Section.
- A closed Section/Subsection may be reopened only for a demonstrated regression, invalidated closure evidence, changed acceptance contract, or a later integration change that demonstrably broke it. Record `REOPENED` and the exact reason before new work begins.
- If two workers close the same scope concurrently, keep one canonical closure lineage/evidence set. Converge any unique necessary changes, then close/supersede the duplicate PR/branch/issue; delete the duplicate branch when safe. Never count one Section twice.
- Before creating a new PR/branch for the current Section, inspect existing active lineages and reuse/repair/converge them when possible.
- If another worker closes the current Section/Subsection while you are working, refresh the live registry immediately. Do not keep mutating already-DONE scope merely because your branch or PR is still open. Preserve and converge only genuinely unique required changes; otherwise close/supersede/retarget the duplicate lineage and move to the earliest unfinished Section.
- External blockers do not justify false DONE. Finish all internally controllable work, record the blocker precisely, and proceed only to dependency-safe work.

Chat history is not closure authority. Durable GitHub state is.
