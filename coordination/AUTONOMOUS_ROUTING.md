# Accessible Chess — Autonomous Routing Control

EPOCH: CHESS-2026-09-07-03
STATE: ACTIVE — FIVE HOURLY WORKERS

## Operating invariant
Every worker, Codex Cloud run and Work run must reconstruct the newest live state before substantive work. Prefer current PR/CI/runtime evidence over stale narrative status. Classify inherited targets as KEEP, CHANGE, STOP_STALE, COLLISION or PROMOTE. Do not duplicate active ownership.

## Product priority
Converge Version 2 formats/library/books/workflows into one genuinely usable Windows/NVDA release candidate without violating Stage 1 accessibility/release boundaries.

Canonical dependency order:
GameTree/PGN -> ACSDB/Library -> ChessBase adapters -> Books/Training -> later Teacher/Classroom/Web.

## Active convergence lineage
PR #435 `V2: complete format integration and production Windows composition` remains the only active umbrella/convergence target. Do not create a competing umbrella unless fresher evidence explicitly supersedes it.

Already integrated / DO NOT REPEAT:
- W2 #436: canonical bounded PGN ingress for BookTraining.
- W3 #437: dirty-PGN open/discard guard preventing silent data loss.
- W4 #438: V2 UI semantic/accessibility CI expansion while preserving the human NVDA boundary.

## W5 major-change update — 2026-09-07
The first composed CI after those integrations exposed two RED gates. Triage proved both failures occurred in historical ancestry/scope assertions before product tests ran:
- `Accessible Chess Version 2 Windows Composition` failed at `Prove exact Version 2 ancestry and collision-safe scope`.
- `D01 PGN Workspace WebView` failed at `Prove exact ancestry and isolated D01 scope`.

These gates were written for isolated historical feature branches and incorrectly required exact commit/file topology that cannot remain true after legitimate convergence into #435. This was a CI integration defect, not evidence of a product regression.

W5 repaired both workflows directly on the existing #435 lineage:
- D01 PGN gate is now integration-aware: it requires the accepted D01 feature ancestry, rejects frozen Stage 1 / strict-release contamination, and then exercises the current integrated PGN workspace/presentation through focused and full tests instead of pinning obsolete commit counts/blob topology.
- V2 Windows composition gate is now convergence-aware: it requires the accepted V2 formats upstream ancestry, rejects frozen Stage 1 / strict-release contamination, requires the composition profile, then runs current composition/accessibility/data/full-repository tests instead of requiring the branch to differ from the old upstream by only three files.

New exact-head CI is running after this repair. Do not classify the old RED runs as current blockers and do not duplicate this CI repair.

## Current release gates
1. New exact-head #435 CI after the integration-aware gate repair must reach terminal GREEN across relevant formats/books/PGN/Windows/accessibility workflows.
2. Any genuine regression found after the ancestry gates pass must be isolated and repaired on #435, not via another umbrella.
3. Produce a fresh Windows candidate/package and exact-machine packaged runtime evidence; never reuse a previously rejected ZIP.
4. Human NVDA acceptance remains open. Only Oleksii can close it on the exact fresh candidate. `NVDA_VERIFIED=NO` until then.
5. ChessBase-family capability truth must remain explicit SUPPORTED/PARTIAL/UNSUPPORTED/BLOCKED; unsupported formats must not hold the desktop release hostage.

## Worker routing
### W1 — Formats / GameTree / interoperability
KEEP. Work only on unowned format/GameTree/interoperability defects or evidence gaps: round-trip, malformed/large-file, capability truth, adapter boundaries and provenance. Do not duplicate #435 or force unsupported formats to SUPPORTED.

### W2 — Library / database / books / training content
KEEP with previous package complete. Do not repeat #436. Take the next unowned preservation/data-loss, Library/Books/Training linkage, recovery/cancellation or integration-evidence package.

### W3 — User workflows / desktop composition
KEEP with previous package complete. Do not repeat #437. Take the next unowned open/save/import/export/review/recovery/analysis/training user-journey defect and preserve canonical chess truth.

### W4 — Windows / NVDA / accessibility / package QA
PROMOTE once new exact-head CI is green. Do not repeat #438. Focus on fresh Windows package/runtime evidence, keyboard-only semantics, focus/labels/state/errors and exact-candidate preparation. Never claim human NVDA verification.

### W5 — Integration / release / coordination
KEEP / PROMOTE. Immediate task: triage the new exact-head CI after the integration-aware gate repair. If GREEN, advance directly to fresh Windows candidate/runtime gates. If RED after product tests actually run, isolate the smallest genuine cross-lane mismatch and repair it on #435. Avoid report-only work when integration is available.

## Codex Cloud / Work
Codex Cloud: take only a disjoint unowned exact-head CI/product integration failure or bounded release-candidate composition package. No second umbrella.

Work: review/implement a high-value cross-layer user-journey or release-evidence package against current #435 that is disjoint from W1-W5 reservations. Persist durable results.

## Hard boundaries
- One canonical chess core; no chess rules inside PGN/ChessBase/books/database/UI/Web adapters.
- No duplicate umbrella/convergence implementation.
- No reuse of rejected Windows ZIPs.
- `NVDA_VERIFIED=NO` until Oleksii personally tests the exact fresh candidate.
- No paid services/compute without explicit owner approval.
- No silent invention/drop of source data.

## Collision control
Before implementation, check current/recent PRs, issues/reports, CI and worker/Codex/Work results. If another active owner has the same semantic package, integrate/review it or take the next unowned package. Completed #436/#437/#438 and the W5 CI-gate repair are DO NOT REPEAT.

## Next audit trigger
Audit immediately if the new exact-head #435 CI becomes materially GREEN/RED, a fresh Windows candidate appears, a major worker/Codex/Work package lands, ownership collides/stales, or routing contradicts fresher evidence. Otherwise perform the normal broader coordination audit about six hours after the prior full audit.
