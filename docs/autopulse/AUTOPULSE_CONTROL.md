# Accessible Chess — AUTOPULSE CONTROL

Version: 2026-08-23
Mode: 10 Product Developers + 1 Coordinator/Integrator + 2 Independent Auditors

## User pulse

The exact same message is valid for every chat:

`СТАРТ. AUTOPULSE. Продовжуй.`

Oleksii is not required to know whether a chat is a developer, coordinator, or auditor before sending the pulse.

## Truth hierarchy

1. Live GitHub exact branch/SHA/diff/PR/Issues/Actions/jobs/logs/artifacts.
2. GitHub Issue #177 `AUTOPULSE CONTROL — 10DEV + COORD + 2AUDIT` plus current lane handoffs.
3. Current Google Drive AUTOPULSE/control documents and role handoffs.
4. Older prompts/reports are historical context only.

Never report an old SHA/CI/blocker as current without checking live GitHub.

## Mandatory pulse algorithm

Every chat performs RECOVER -> DECIDE -> COLLISION CHECK -> EXECUTE -> VERIFY -> PUBLISH.

### RECOVER
- identify permanent role/lane from bootstrap prompt and existing branch/PR/handoff;
- inspect own last unfinished run first;
- read Issue #177, recent PRs/branches/Actions, relevant current Drive handoffs;
- detect active owners and file overlap before Product edits.

### DECIDE
Priority: P0 release/security/data-loss/accessibility/architecture -> P1 functionality -> P2 polish/performance.
Resume an unfinished own run before opening a new one.
If complete, choose the largest coherent unclaimed package in the permanent lane.
Do not wait merely because Coordinator/Auditor prose is stale or absent.

### COLLISION CHECK
Before Product mutation, inspect open PRs and recent branches touching intended Product files.
If another active owner already touches the same Product surface, do not duplicate it. Validate it, choose a disjoint safe-overlap package, or take the next backlog item.
Never force-push shared history.

### EXECUTE
Use large coherent packages. Read relevant code/tests first. Implement Product + regressions + integration evidence in the same run where feasible. Do not weaken tests for GREEN. Do not invent Windows or NVDA evidence.

### VERIFY
Run focused tests, broader regressions, and applicable hosted CI. Classify RED as Product / QA-environment / stale evidence / inconclusive before patching. Windows release candidate WIP remains 1.

### PUBLISH
Before ending every run, including WAITING/NO-CHANGE, leave durable state: branch/commits; PR/evidence surface when useful; concise handoff with UTC/local time, branch/SHA, changes, tests/CI, blockers, ownership and next action. No useful work may exist only in chat text.

## Fail-open coordination

- Coordinator missing/stale -> Developers/Auditors continue from live GitHub.
- Auditor missing/stale -> Developers continue ordinary Product work; only explicit release/merge acceptance gates wait where required.
- Developer missing/stale -> other lanes continue; Coordinator/Auditors inspect available evidence and route/identify non-overlapping work.
- Drive handoff missing -> recover from GitHub and continue.
- CI running -> do not duplicate/retrigger just for speed; take genuinely non-overlapping work.

## Role topology

- D01 Windows UI / Accessibility / NVDA / Action Routing
- D02 Canonical Core / Position / History / Atomicity
- D03 Stockfish / Engine Play / Analysis / Clocks / Lifecycle
- D04 Packaging / Security / Resources / Release Preflight / File Safety
- D05 Integration / Composition / Release Engineering / Cross-Lane Regression
- D06 PGN / GameTree persistence / comments / NAG / RAV / round-trip
- D07 ACSDB / Library / Search / migrations / performance
- D08 Books / Training / structured diagrams / exercises
- D09 Teacher / Classroom / visual board / pointer / student interaction
- D10 Classes / Students / Lessons / Assignments / Progress / Remote Sessions
- COORD Global Coordinator / Selective Integrator / Collision Resolver
- AUDIT-A Independent Release / Windows / NVDA / Security / Artifact audit
- AUDIT-B Independent Architecture / Data Integrity / Cross-Lane / Full-Product audit

## Independence and ownership

Auditors do not patch Product code. They may create QA/evidence tests/workflows, inspect diffs/logs/artifacts, post exact findings, and route exact repairs.
Coordinator may selectively integrate evidence-backed packages, resolve collisions and maintain the global live board, but is not a single point of failure for ordinary development.

## Core invariants

Windows-only product. NVDA release-critical. One canonical chess/application core. Move Input, Teacher Pointer, Position Editor and Annotation are distinct. Pointer/highlight/arrow/hover do not mutate chess position. 64 logical squares remain unique/accessibile/keyboard navigable. Normal Ctrl+A/Ctrl+C/selection must work. No live-region spam, raw traceback, private local paths, UCI/provider internals in user-facing text. Invalid move/FEN/editor/import operations remain atomic.

## Release invariant

Old human-rejected ZIP is forbidden. `NVDA_VERIFIED=NO` until Oleksii personally tests the exact fresh machine-green candidate. Before user handoff the exact current Audit-accepted Stage1 source must pass combined validation, strict packaged Windows/UIA, sound/Stockfish lifecycle, release preflight, ZIP reopen/hash/identity and artifact checks.

## Bootstrap snapshot only

At AUTOPULSE bootstrap the project is in Stage1 release freeze. Stockfish runtime privacy repair and DEV2 history fail-closed repair have individual Audit acceptance; a combined Stage1 repair line exists and must become the exact validated/audited authority before a final human candidate. Every pulse must verify live state and supersede this snapshot when GitHub advances.
