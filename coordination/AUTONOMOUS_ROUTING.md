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
- W3 #439: Windows file-workflow action dispatch is fail-closed off the owning UI thread; the package reached terminal GREEN on Ubuntu and Windows before intake into #435.

STOP_STALE / do not revive:
- W4 #440: convergence-aware Windows-composition gate child is superseded because the equivalent integration-aware repair already landed directly on #435.

Active temporary reservations / collision boundaries:
- #441 owns `Version2Application`, PGN selected-position/export command composition, detached Library game opening, import observer/terminal UI, Book workspace binding, and the actual V2 Windows launcher/bootstrap. Do not duplicate these surfaces; integrate/review #441 when its exact checks complete.
- #442 owns automated Windows/NVDA package/runtime QA on the #441 lineage only; it does not own Product launcher code and may not claim human NVDA acceptance.
- #443 is W3's narrow owner-bound dirty-PGN confirmation package. It changes only the native Windows ownership adapter and focused regression coverage; do not duplicate it while CI is pending.

## W5 major-change update — 2026-09-07
The first composed CI after those integrations exposed two RED gates. Triage proved both failures occurred in historical ancestry/scope assertions before product tests ran:
- `Accessible Chess Version 2 Windows Composition` failed at `Prove exact Version 2 ancestry and collision-safe scope`.
- `D01 PGN Workspace WebView` failed at `Prove exact ancestry and isolated D01 scope`.

These gates were written for isolated historical feature branches and incorrectly required exact commit/file topology that cannot remain true after legitimate convergence into #435. This was a CI integration defect, not evidence of a product regression.

W5 repaired both workflows directly on the existing #435 lineage:
- D01 PGN gate is now integration-aware: it requires the accepted D01 feature ancestry, rejects frozen Stage 1 / strict-release contamination, and then exercises the current integrated PGN workspace/presentation through focused and full tests instead of pinning obsolete commit counts/blob topology.
- V2 Windows composition gate is now convergence-aware: it requires the accepted V2 formats upstream ancestry, rejects frozen Stage 1 / strict-release contamination, requires the composition profile, then runs current composition/accessibility/data/full-repository tests instead of requiring the branch to differ from the old upstream by only three files.

Current #435 exact head after #439 intake has terminal GREEN for UI Semantic Gate, V2 Windows Composition, D01 PGN Workspace and Books/Training UI. The broad V2 Formats Integration workflow is still running at this checkpoint. Do not classify the old RED runs as current blockers and do not duplicate this CI repair.

## Current release gates
1. New exact-head #435 CI after the integration-aware gate repair must reach terminal GREEN across relevant formats/books/PGN/Windows/accessibility workflows.
2. Any genuine regression found after the ancestry gates pass must be isolated and repaired on #435, not via another umbrella.
3. Converge the active #441 application/launcher user-journey package with all accepted #435 children without losing their histories or tests.
4. Produce a fresh Windows candidate/package and exact-machine packaged runtime evidence; never reuse a previously rejected ZIP.
5. Human NVDA acceptance remains open. Only Oleksii can close it on the exact fresh candidate. `NVDA_VERIFIED=NO` until then.
6. ChessBase-family capability truth must remain explicit SUPPORTED/PARTIAL/UNSUPPORTED/BLOCKED; unsupported formats must not hold the desktop release hostage.

## Worker routing
### W1 — Formats / GameTree / interoperability
KEEP. Work only on unowned format/GameTree/interoperability defects or evidence gaps: round-trip, malformed/large-file, capability truth, adapter boundaries and provenance. Do not duplicate #435 or force unsupported formats to SUPPORTED.

### W2 — Library / database / books / training content
KEEP with previous package complete. Do not repeat #436. Take the next unowned preservation/data-loss, Library/Books/Training linkage, recovery/cancellation or integration-evidence package. Avoid #441-owned Library/import/Book application composition.

### W3 — User workflows / desktop composition
KEEP. Do not repeat #437/#439. #443 currently owns the native dirty-PGN confirmation modality/focus gap. Do not duplicate #441 launcher/application/import observer work. After #443 terminalizes, take the next disjoint user-journey defect or help integrate accepted W3 packages into the canonical lineage.

### W4 — Windows / NVDA / accessibility / package QA
PROMOTE. Do not repeat #438/#440. #442 is the active automated Windows/NVDA runtime/package-QA child of #441. Never claim human NVDA verification.

### W5 — Integration / release / coordination
KEEP / PROMOTE. Triage broad exact-head Formats Integration when terminal, then converge terminal children into #435/#441 without spawning another umbrella. If GREEN, advance directly to fresh Windows candidate/runtime gates. If RED after product tests actually run, isolate the smallest genuine cross-lane mismatch and repair it on the canonical lineage.

## Codex Cloud / Work
Codex Cloud: take only a disjoint unowned exact-head CI/product integration failure or bounded release-candidate composition package. No second umbrella.

Work: review/implement a high-value cross-layer user-journey or release-evidence package against current #435 that is disjoint from #441/#442/#443 and W1-W5 reservations. Persist durable results.

## Hard boundaries
- One canonical chess core; no chess rules inside PGN/ChessBase/books/database/UI/Web adapters.
- No duplicate umbrella/convergence implementation.
- No reuse of rejected Windows ZIPs.
- `NVDA_VERIFIED=NO` until Oleksii personally tests the exact fresh candidate.
- No paid services/compute without explicit owner approval.
- No silent invention/drop of source data.

## Collision control
Before implementation, check current/recent PRs, issues/reports, CI and worker/Codex/Work results. If another active owner has the same semantic package, integrate/review it or take the next unowned package. Completed #436/#437/#438/#439 and the W5 CI-gate repair are DO NOT REPEAT. #440 is STOP_STALE. #441/#442/#443 are live reservations at this checkpoint.

## Next audit trigger
Audit immediately if the broad #435 Formats Integration becomes materially GREEN/RED, #441 advances or converges, #442 produces exact Windows runtime evidence, #443 terminalizes, a fresh Windows candidate appears, ownership collides/stales, or routing contradicts fresher evidence. Otherwise perform the normal broader coordination audit about six hours after the prior full audit.
