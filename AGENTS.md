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
