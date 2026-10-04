# Accessible Chess — Five-worker Fast-Lane Release Train v2

Effective: 2026-08-15 Europe/Kyiv

## Goal
Reduce release latency without creating moving-target merges or duplicating ownership.

## Worker ownership
- Worker 1: UI/NVDA — `dev/stage1-nvda-webview-0.4.0`
- Worker 2: Engine/Core — `dev/stage1-engine-core-0.4.0`
- Worker 3: Data/ChessBase — `dev/stage2-data-core`
- Worker 5: Integration/Candidate — `integration/accessible-chess-next`
- Worker 4: QA/Windows Release/Security — locked QA/release branches only

## Release-train protocol
Each producer has two distinct pointers:
- `WORK_HEAD`: moving development head.
- `CANDIDATE_HANDOFF_SHA`: frozen exact passing commit for the current release wave.

Worker 5 integrates only explicit frozen passing handoffs. Newer source commits are not automatically candidate material.

After integration, Worker 5 records `CONSUMED_BY_INTEGRATION=<sha>` so the producer can safely advance release-sensitive files.

Worker 4 packages only an exact green integration SHA explicitly marked `READY_FOR_WORKER4_WINDOWS_BUILD`. A Windows candidate branch is product-code frozen for the duration of the attempt.

## Merge strategy
Do not wholesale-merge heavily diverged branches solely to become current. Use merge-base comparison and selective feature transplant/cherry-pick/patch groups by ownership surface. Preserve newer integration contracts and use narrow compatibility adapters where necessary. Run focused gates after each group and then the full integration gate.

## Current release wave baseline
- UI frozen handoff: `6bb22e85e9afa41f68a93180f955a2850be04b86` — UI Semantic Gate `31884063886` SUCCESS.
- Core frozen handoff: `503b768a9a3358a13de09e906b9dc3e9320c95a1` — Engine Core CI `31884140863` SUCCESS.
- Integration baseline: `a6b8bc43e5233e8e6c73459623ae97d14dba1232` — Integration Core `31885025162` SUCCESS.
- Windows attempt #36 / `31885952278` executed 361 tests and exposed two Data/import blockers:
  1. ACSDB newer-schema rejection leaves a Windows SQLite handle open (WinError 32 cleanup).
  2. ChessBase provenance path is not normalized to stable forward-slash form on Windows.

Worker 3 owns these fixes; Worker 5 integrates the resulting frozen Data handoff; Worker 4 re-locks and reruns Windows release validation.

## CI speed rules
Use workflow-level concurrency with `cancel-in-progress: true` on fast source/integration CI so superseded runs are cancelled. Do not use that policy to cancel an already valid locked Windows release attempt. Prefer candidate locking for expensive Windows builds.

## Quality rules
- No test weakening to obtain green.
- No `NVDA VERIFIED` claim before Oleksii's real NVDA test.
- Automated package label only: `NVDA TEST CANDIDATE — WAITING FOR USER TEST`.
- No big-bang rewrite.
- No duplicate ownership coding.
