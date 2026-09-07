# Accessible Chess — Autonomous Routing Control

EPOCH: CHESS-2026-09-07-01
STATE: ACTIVE — OWNER REACTIVATED 2026-09-07
CADENCE: five productive workers wake hourly; full coordination audit about every 6 hours or immediately after a major change; failover audit if the normal audit is stale for about 8 hours.

## Operating invariant
Oleksii must not have to manually rewrite five worker prompts after every change. Every worker, Codex Cloud run, and Work run must reconstruct the newest live state before substantive work, then use this file as the shared routing surface. Prompt text is a stable role definition, not a frozen task list.

Before substantive work, each worker must inspect the newest relevant evidence: current/default branch, active integration/release branches, open and recently closed pull requests, current issues/status reports, CI/runtime evidence, this routing file, `docs/GLOBAL_COORDINATOR_BRIDGE.md`, `docs/TECHNICAL_ROADMAP.md`, and recent Work/Codex results if visible. Prefer fresher concrete evidence over stale narrative status.

Classify any inherited target as one of: KEEP, CHANGE, STOP_STALE, COLLISION, PROMOTE. Never continue a stale assignment merely because it appears in an old prompt.

## Current product priority
Accessible Chess is ACTIVE again by explicit owner instruction on 2026-09-07.

Near-term goal: converge the Version 2 formats/library work into a genuinely usable Windows/NVDA release candidate without losing the existing Stage 1 accessibility/release constraints.

Canonical dependency order remains:
GameTree/PGN -> ACSDB/Library -> ChessBase adapters -> Books/Training -> Teacher/Classroom -> later Web/server work.

Do not allow future Web/Classroom scope to delay the current desktop/formats release path.

## Fresh live evidence at activation
- Draft PR #435, `V2: complete format integration and production Windows composition`, is a current convergence lineage and was updated on 2026-09-07. It already composes accepted format/PGN work and is continuing Books integration, production root and composed CI. Treat it as active ownership until newer evidence changes that conclusion; do not create a competing umbrella implementation.
- Issue #14 is an older Stage 1 status surface. Its enduring release constraints still matter, especially: never reuse a human-rejected Windows ZIP; `NVDA_VERIFIED=NO` until Oleksii tests the exact fresh candidate; accessibility evidence must be real. Where #14's task ownership/status conflicts with newer 2026-09-07 evidence, reconstruct the live state rather than blindly following the old assignment.
- The technical roadmap keeps Windows/NVDA first-class and requires one canonical chess/application truth shared by formats, library, books and later Web surfaces.

## Do not repeat / hard boundaries
1. Do not reissue any previously human-rejected Windows ZIP.
2. Never claim `NVDA_VERIFIED=YES` without Oleksii personally testing the exact candidate.
3. Do not create a second umbrella/convergence branch that duplicates a live owner such as PR #435.
4. Do not implement separate chess rules inside PGN, ChessBase, books, database, Windows UI or future Web adapters.
5. Do not silently invent/drop source data; use explicit SUPPORTED/PARTIAL/UNSUPPORTED/BLOCKED capability truth and ImportReport-style evidence.
6. Do not let speculative Web/commercial work outrank the current Windows + formats/library release path.
7. Do not use paid services/compute or incur costs without Oleksii's explicit authorization.

## Temporary ownership / collision control
Before a material implementation package, check current ownership and recent work. A package is a temporary reservation, not permanent territory. Record or refresh, using the project's available durable coordination surface, at least: worker, exact scope, lineage/branch or target, last refresh, next checkpoint, expiry/staleness rule, and state. Release or update the reservation when completed, blocked, superseded or stale.

If another active worker/Codex/Work already owns the same package, do not duplicate it. Review/integrate that lineage if useful, or take the next highest-priority unowned package in your lane.

## Stable productive lanes
### W1 — Formats / GameTree / interoperability
Own high-value unowned work around canonical GameTree/PGN, import/export correctness, ChessBase-family adapters where technically/legal feasible, provenance, round-trip/malformed-input/large-file tests, explicit support reporting and format boundaries. Do not duplicate the active PR #435 convergence owner; work on disjoint defects/gates or review/integration-ready evidence.

### W2 — Library / database / books / training content
Own ACSDB/library/search/index/import workflows, migrations/data-loss safety, semantic Books/BookReader/training content, positions/games/variation linkage, progress/cancellation/recovery, provenance/dedupe, and integration tests. Respect canonical GameTree and current convergence ownership.

### W3 — User workflows / desktop composition
Own unowned user-visible desktop workflows that connect the canonical core to actual use: game review/navigation, open/save/export/import UX, position/history recovery, analysis/training workflow, error/cancel/resume semantics, and production composition seams. Do not fork chess truth or duplicate W1/W2 domain work.

### W4 — Windows / NVDA / accessibility / package QA
Own keyboard-only and screen-reader accessibility, focus/labels/state/errors, Windows packaging/install/startup, packaged E2E, exact-candidate smoke/regression evidence, release artifact hygiene and human acceptance preparation. Never set `NVDA_VERIFIED=YES`; only Oleksii can close that human gate on the exact candidate.

### W5 — Integration / release / coordination
Remain a productive integration developer. Own cross-lane composition, CI/interface mismatches, candidate convergence, release gating, stale/collision detection and integration-ready cleanup. Perform a full coordination audit only when due: no valid audit exists, about 6 hours elapsed, or a major-change trigger occurs. If the normal audit is missing for about 8 hours, perform a failover audit. Otherwise implement/integrate rather than spending the whole run reporting.

## Major-change triggers
Refresh routing immediately when any of these happens:
- a large Work or Codex package completes;
- the active convergence/candidate lineage changes materially;
- a major blocker opens/closes;
- Windows/package/NVDA readiness changes;
- a collision or stale reservation is discovered;
- a major format/library gate becomes green/red;
- current routing contradicts fresher live evidence.

## Full audit output
When an audit is due, persist a concise updated control state containing:
- EPOCH and current stage;
- what materially changed since the previous audit;
- completed/do-not-repeat items;
- top blockers and release gates;
- W1-W5 current targets;
- current temporary ownership/reservations and stale/collision decisions;
- active integration/candidate lineage;
- separate safe package for Codex Cloud if useful;
- separate high-value Work package/review if useful;
- Windows/package/NVDA readiness truth;
- next audit trigger/window;
- a short owner-facing summary in plain Ukrainian.

## Every hourly worker run
1. Read this routing file and reconstruct fresher live state.
2. Check current/recent PRs, reports, CI and reservations before touching code.
3. Classify inherited work KEEP / CHANGE / STOP_STALE / COLLISION / PROMOTE.
4. Take the highest-priority useful unowned package in the worker's lane; if the lane is temporarily exhausted, help integration without duplicating ownership.
5. Implement a coherent package, test it, and persist durable evidence/checkpoint.
6. Update routing/ownership when the project state materially changes.
7. End with a concise Ukrainian owner report: current stage, what changed, what is next, blocker, and whether Oleksii must act. Do not burden him with branch/SHA/PR mechanics unless needed for a decision.

## Codex Cloud and Work
If Codex Cloud or Work enters the project, it must read this same live routing and current ownership first, take a disjoint high-value package, leave durable checkpoints after coherent phases, and update routing/recommendations after a major state change. Scheduled workers must then reconstruct the new live state on their next wake rather than repeat the finished work.
