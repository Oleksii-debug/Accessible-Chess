# Codex autonomous NEXT_WORK — DEV4 QA/evidence — 2026-08-23

Live GitHub and AUTOPULSE Issue #177 supersede older queue prose.

## Immediate P0

1. Do not rerun PR #175 on obsolete final-candidate source `1e9d23b...`; it is evidence only after the accepted DEV2 history repair required a combined source.
2. Let the current combined Stage1 line `release/dev5-stage1-combined-repair-20260823@574d8c7344a7490de46ba38498f363395c951019` finish exact validation/audit under its owner. Do not compete with active Product/integration ownership.
3. Preserve Windows WIP=1. When the combined source is exact validated/audited and the current Windows slot is free, execute exactly one fresh packaged chain on that exact SHA.
4. Keep the strict assertions that already proved native Backspace, Ctrl+A and Ctrl+C. Never weaken or remove them.
5. Re-test the retained board-focus continuity assertion after the pure submit bridge. If the exact combined packaged candidate again leaves semantic focus on `move-input` instead of the board, route the minimal Product repair to D01/current UI owner; DEV4 QA remains evidence-only for that UI surface.

## Current classifications

- `PROVEN_PRODUCT_DEFECT` on packaged `1e9d23b...`: board-focus continuity after submit bridge fails cross-process UIA.
- Ctrl+A/Ctrl+C: proven PASS on the same packaged run; not a Product defect.
- `HUMAN_ONLY`: native menu usability with Alt/Arrows/Enter/Esc + NVDA.
- Combined `574d8c7...` exact packaged focus state: not yet proven; requires its own candidate run.

## Safe-overlap work while Windows WIP is occupied

Continue independent non-conflicting review of current Full Product branches for false-green/data-loss/security boundaries, prioritizing PGN/GameTree round-trip and atomicity, ACSDB migration/search contracts, ChessBase-family provenance/file safety, packaging/resource assumptions, user-facing path/traceback/UCI leakage, and engine lifecycle/race evidence. Add QA-only tests/evidence only when they do not overlap an active owner.

## Release invariants

`FRESH_WINDOWS_CANDIDATE=NO`
`READY_FOR_RELEASE=NO`
`NVDA_VERIFIED=NO`

Old rejected ZIP remains forbidden. Only Oleksii can provide human NVDA verification on the exact fresh machine-green candidate.
