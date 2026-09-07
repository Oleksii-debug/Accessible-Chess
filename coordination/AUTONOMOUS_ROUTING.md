# Accessible Chess — Autonomous Routing Control

EPOCH: CHESS-2026-09-07-02
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

## Current live convergence state — W5 audit 2026-09-07
- PR #435, `V2: complete format integration and production Windows composition`, remains the active umbrella/convergence lineage and is mergeable. Do not create a competing umbrella.
- W2 package #436 was selectively integrated into #435. It removes a remaining BookTraining bypass of canonical bounded D06 PGN ingress and retains fail-closed structured-solution behavior.
- W3 package #437 was selectively integrated into #435. It closes a user-visible data-loss path: opening another PGN can no longer silently replace a dirty `PgnDocumentSession`; explicit discard confirmation is required and refusal preserves session/focus.
- W4 package #438 was selectively integrated into #435. The existing UI semantic/accessibility gate now covers active V2 Windows presentation paths and runs the established semantic suite on both Ubuntu and Windows while preserving the human NVDA boundary.
- After those three integrations the #435 head advanced and composed CI restarted. At the time of this audit the new integration workflows were still running; do not treat the composed candidate as terminal GREEN until exact-head CI finishes.
- No new Windows ZIP was produced or accepted. `NVDA_VERIFIED=NO` remains mandatory until Oleksii personally tests the exact fresh candidate.

## Classification from this audit
- PR #435 umbrella/convergence lineage: KEEP / PROMOTE as the only active integration target.
- W2 #436 canonical BookTraining ingress package: PROMOTE completed into #435; DO NOT REPEAT.
- W3 #437 unsaved-PGN Open guard: PROMOTE completed into #435; DO NOT REPEAT.
- W4 #438 V2 UI semantic gate expansion: PROMOTE completed into #435; DO NOT REPEAT.
- Competing umbrella implementations against #435: COLLISION / STOP_STALE unless fresher evidence explicitly supersedes #435.
- Old Stage 1 status ownership in Issue #14: KEEP only for enduring release constraints; CHANGE any stale task ownership when contradicted by current V2 evidence.

## Current top blockers / release gates
1. Exact-head composed CI for the newly integrated #435 candidate must finish and remain GREEN across relevant format/library/books/Windows/accessibility gates.
2. Any integration regression exposed by the composed run must be repaired on the same convergence lineage, not via another umbrella.
3. A fresh Windows package/candidate still needs exact-machine packaged runtime evidence before human acceptance.
4. Human NVDA acceptance remains open and can only be closed by Oleksii on the exact fresh candidate.
5. Blocked/partial ChessBase-family capabilities must remain honestly reported; do not delay the desktop release merely to force unsupported formats to SUPPORTED.

## Do not repeat / hard boundaries
1. Do not reissue any previously human-rejected Windows ZIP.
2. Never claim `NVDA_VERIFIED=YES` without Oleksii personally testing the exact candidate.
3. Do not create a second umbrella/convergence branch that duplicates live #435.
4. Do not reimplement the completed W2 #436, W3 #437 or W4 #438 packages; they are already integrated into #435.
5. Do not implement separate chess rules inside PGN, ChessBase, books, database, Windows UI or future Web adapters.
6. Do not silently invent/drop source data; use explicit SUPPORTED/PARTIAL/UNSUPPORTED/BLOCKED capability truth and ImportReport-style evidence.
7. Do not let speculative Web/commercial work outrank the current Windows + formats/library release path.
8. Do not use paid services/compute or incur costs without Oleksii's explicit authorization.

## Temporary ownership / collision control
Before a material implementation package, check current ownership and recent work. A package is a temporary reservation, not permanent territory. Record or refresh, using the project's available durable coordination surface, at least: worker, exact scope, lineage/branch or target, last refresh, next checkpoint, expiry/staleness rule, and state. Release or update the reservation when completed, blocked, superseded or stale.

If another active worker/Codex/Work already owns the same package, do not duplicate it. Review/integrate that lineage if useful, or take the next highest-priority unowned package in your lane.

## Current worker routing after W5 integration
### W1 — Formats / GameTree / interoperability
KEEP lane. Reconstruct the new #435 head before work. Take the highest-value unowned format/GameTree/interoperability defect or evidence gap that does not duplicate the umbrella. Prefer round-trip, malformed/large-file, capability-truth or adapter-boundary work that can be selectively integrated. Do not block release on formats that remain legitimately BLOCKED/PARTIAL.

### W2 — Library / database / books / training content
CHANGE from #436 because that package is complete and integrated. Reconstruct #435 and take the next unowned Library/Books/Training defect or integration gap. Do not repeat canonical BookTraining ingress. Prioritize preservation/data-loss safety, semantic reading/training linkage, recovery/cancellation and cross-layer integration evidence.

### W3 — User workflows / desktop composition
CHANGE from #437 because that package is complete and integrated. Reconstruct #435 and take the next unowned user-visible desktop workflow defect. Do not repeat the unsaved-PGN Open guard. Prioritize real open/save/import/export/review/recovery/analysis/training flows and fail-closed behavior.

### W4 — Windows / NVDA / accessibility / package QA
CHANGE from #438 because that package is complete and integrated. Reconstruct #435 and inspect the new exact-head semantic/accessibility CI. Take the next unowned accessibility/package/runtime gap. Prepare fresh exact-candidate evidence but never claim human NVDA verification.

### W5 — Integration / release / coordination
KEEP / PROMOTE integration ownership on #435. Current immediate task is composed exact-head CI triage after intake of #436/#437/#438. If GREEN, advance the candidate toward fresh Windows package/runtime gates. If RED, isolate the smallest cross-lane mismatch and repair/integrate on the same lineage. Avoid report-only work when real integration is available.

## Codex Cloud and Work routing
- Codex Cloud: if invoked, first read this routing and the current #435 state. Safe high-value package: an unowned exact-head CI/integration failure or a bounded release-candidate composition gap. Do not create a new umbrella or repeat #436/#437/#438.
- Work: if invoked, perform a high-value review/implementation package against the current #435 candidate, preferably cross-layer user-journey/release evidence that is disjoint from active worker reservations. Persist durable results so hourly workers can consume them.

## Windows / package / NVDA truth
- Active candidate lineage: #435.
- Fresh exact-head composed CI: RUNNING at this audit after three worker integrations; terminal verdict not yet claimed.
- Fresh Windows ZIP accepted by owner: NO.
- Human exact-candidate NVDA test completed: NO.
- `NVDA_VERIFIED=NO`.
- No previously rejected artifact may be reused.

## Stable productive lanes
### W1 — Formats / GameTree / interoperability
Own high-value unowned work around canonical GameTree/PGN, import/export correctness, ChessBase-family adapters where technically/legal feasible, provenance, round-trip/malformed-input/large-file tests, explicit support reporting and format boundaries. Do not duplicate the active #435 convergence owner; work on disjoint defects/gates or review/integration-ready evidence.

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

## Next audit trigger/window
Normal next full audit: about six hours after this W5 audit. Audit immediately sooner if the exact-head #435 CI turns RED/GREEN in a way that changes the critical path, a new Windows candidate/package appears, a major Work/Codex package lands, or worker ownership collides/stales.
