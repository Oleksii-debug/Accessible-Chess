# Codex autonomous NEXT_WORK

This is a priority queue, not a one-fix ticket. Complete the largest safe verified package, checkpoint, then continue automatically.

## P0 — restore exact current Stage1 head to green

Start from `codex/autonomous-20260821`, which contains Product head `498989b4...` plus documentation-only bootstrap commits.

1. Reproduce both exact latest failures locally and read the relevant implementation/tests before patching.
2. Fix the native-menu proxy / release-window contract correctly. Do not merely loosen the test. Preserve one central action path and compatibility with real release composition/test doubles where architecturally intended.
3. Fix the keymap-editor search regression correctly. Determine whether the newly localized rank/file labels should match generic `перейти`; preserve useful localized search while maintaining deterministic UX. Update implementation and/or expectation only after establishing the intended contract.
4. Run all focused gates, then full unittest, full pytest, complete diagnostic.
5. Push a checkpoint and verify GitHub Actions for the exact new head. Do not call the branch green until both current PR gates are green for the same exact SHA.

## P0 — close remaining machine-verifiable Stage1 release blockers

After exact current Product saturation is green:

1. Audit all Stage1 canonical requirements against live code and tests, not old reports.
2. Close missing/partial board command reachability, central Action Registry consistency and discoverability/remapping/help.
3. Audit native menu routing: actions that have central IDs should converge on central dispatch; presentation-only native behavior may remain native. No duplicate chess-state logic.
4. Stress Move Input, board focus, history/review/variations, undo/redo, FEN and Position Editor with long sequences and adversarial invalid inputs.
5. Stress Stockfish ownership, levels 1–10, white/black/random side, stale/race suppression, clocks, takeback, resign/draw/terminal outcomes, engine failure recovery and analysis MultiPV.
6. Stress sound event ordering, real runtime path, disable/zero-volume behavior, preview and failure isolation.
7. Audit user-facing text for raw exceptions, local paths, migration/developer prose or background live-region spam.
8. Audit packaging assumptions introduced by `*_core.py`, additional JS resources and native-menu proxy under Nuitka/Windows resource collection.
9. Read live Issue #14, #22, #45 and current strict QA branch before changing release/QA automation.

### Windows strict blocker

The last verified strict run was C/inconclusive because the QA helper failed restoring ValuePattern state before decisive Ctrl+A/Ctrl+C proof. Native Backspace delivery was already proved. Do not invent a Product clipboard defect.

If Codex has a Windows-capable local environment and the repository permissions to run/repair the QA workflow, it may advance the QA-owned strict blocker in a separate QA worktree/branch, preserving WIP=1 and exact source locks. Otherwise record the exact external limitation and continue independent Product work.

A new exact candidate may be produced only after the full machine release chain passes. It must still carry `nvda_verified=false` until human acceptance.

## P1 — full-product critical-path work when Stage1 is human-blocked or machine-green

Do not sit idle waiting for human NVDA acceptance. Use a separate worktree/branch and advance the canonical Windows roadmap while preserving Stage1 isolation.

First inventory and compare existing future-work branches such as:
- `completion/full-product-critical-path-20260819`
- `dev/stage2-data-core`
- `integration/data-forward-acsdb-v3`
- `feature/teaching-classroom-foundation`
- `integration/teaching-classroom-next`
- other relevant live branches discovered from GitHub.

Reuse proven work rather than rewriting it. Never merge a future branch wholesale without diff/test/architecture review.

Priority order for implementation:

### A. Canonical core and full PGN/GameTree
- legal canonical state and application-command boundaries;
- comments, NAGs, nested RAV, headers/results and full round-trip preservation;
- atomic open/save/export with source provenance and lost-update protection;
- accessible review/variation navigation over the same GameTree.

### B. ACSDB / Library / Search
- versioned schema/migrations and corruption/newer-schema handling;
- provenance and import reports;
- games/positions/tags/search with parameterized queries and stable paging;
- import/export round trips and failure atomicity.

### C. ChessBase compatibility
- isolate CBH/CBV/CBF/component-family adapters;
- capability matrix and explicit unsupported states;
- never claim lossless support from extension alone;
- family integrity/provenance checks before import.

### D. Books and training
- semantic linear book model, accessible structured diagrams/positions;
- exercises, variations and exact return points;
- preserve canonical chess state; no graphical board dependency for essential meaning.

### E. Teacher/Classroom
- blind-teacher-first keyboard/NVDA workflows;
- sighted-student visual board driven by canonical state;
- Keyboard Visual Pointer separate from Move Input; typing `f3` points to f3 and auto-clears without mutating position;
- highlights/arrows/legal-move highlighting/coordinate toggle;
- student hover and click/selection as distinct reverse-channel events to NVDA;
- explicit modes decide when a student click may become a chess move;
- classes/students/groups/lessons/exercises/assignments/progress.

### F. Remote/shared lessons
Only after local contracts above are stable: shared sessions, explicit authority/ownership, recoverability, disconnect/reconnect safety and accessibility.

## P2 — quality, security and maintainability sweep

Continuously, and especially when implementation lanes are blocked:
- broaden property/adversarial/regression tests around changed boundaries;
- security/privacy/path/secret/error-surface review;
- import/package/resource analysis;
- dead-code and duplicate-source-of-truth audit;
- performance checks for large histories/databases without sacrificing determinism;
- documentation updates only where they preserve durable engineering context.

## Parallelization

If Codex supports multiple agents/worktrees, use separate ownership domains:
- Release/Stage1 lane: current Codex branch and strict Windows/release closure.
- Full-product lane: isolated future branch/worktree after auditing existing future work.
- QA/evidence lane: tests, adversarial sweeps, CI/log review, no competing edits to the same implementation files.

Never have parallel agents edit the same files blindly. Merge only after exact diff review and tests.

## Stop condition

Do not stop because one task passed. Continue until one of these is true:
- available Codex usage/session ends;
- every currently READY task in the canonical roadmap is completed and verified;
- only real external/human blockers remain.

Before stopping, update `CURRENT_STATE.md` and this file with exact branches, SHAs, CI runs, test counts, unresolved defects and the next executable action.