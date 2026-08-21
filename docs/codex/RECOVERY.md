# Codex checkpoint, recovery and return protocol

The user intends to leave Codex running temporarily and then return to the normal manual Developer/Auditor workflow. Preserve enough exact state that no conversation transcript is needed to resume.

## Persistent checkpoint cadence

After every coherent atomic result or approximately every 10–15 minutes of valuable implementation, whichever comes first:
1. run the fastest relevant verification;
2. inspect `git diff --check`;
3. commit with a descriptive message;
4. push to a persistent remote branch;
5. continue working.

Before risky refactors, schema migrations, packaging changes or broad merges, make and push a safe pre-change checkpoint first.

Never force-push checkpoint history. Never leave hours of useful work only in an unpushed worktree/stash.

## Branch/worktree naming

Prefer clear persistent names such as:
- `codex/stage1-release-20260821`
- `codex/full-product-20260821`
- `codex/qa-evidence-20260821`

If an existing Codex branch already owns the same lane, reuse it instead of spawning duplicates.

## When a lane is blocked

Record:
- exact branch and SHA;
- failing command/workflow/run/job;
- exact observed error;
- classification: Product defect / QA harness defect / environment limitation / human-only blocker / external dependency;
- what has already been ruled out;
- next executable action.

Then move to the highest-priority independent READY package. Do not stop the whole session because one lane is blocked.

## CI discipline

A local green state is not enough when GitHub CI exists. Inspect CI for the exact pushed SHA. If CI is red, diagnose it before calling the package complete. Avoid repeated blind reruns; rerun only when failure is plausibly transient.

For strict Windows release work, preserve WIP=1. Do not create multiple concurrent strict candidate runs.

## End-of-session mandatory handoff

Before Codex stops because of usage/session limits or a genuine global blocker:

Update `docs/codex/CURRENT_STATE.md` with:
- session end UTC timestamp;
- every active Codex branch/worktree;
- exact head SHA of each;
- PRs created/updated;
- CI run IDs and conclusions;
- full/targeted test counts;
- Windows artifact/candidate status;
- `NVDA_VERIFIED=NO` unless the user explicitly performed the exact human test (normally it remains NO during this autonomous session);
- completed roadmap packages;
- unresolved P0/P1/P2 defects and exact blockers.

Update `docs/codex/NEXT_WORK.md` so its top section is the exact next executable package, not a stale plan.

Create or update `docs/codex/SESSION_HANDOFF.md` containing a compact final summary suitable for the manual Developer/Auditor chats to read without Codex conversation history.

Commit and push these handoff files.

## Return command for the human

After Codex stops, the user should only need to return to the manual audit chat and say:

`Codex закінчив. Є на GitHub.`

The auditor will read these repo-native handoff files plus live GitHub state and continue from exact evidence. No ZIP, copied logs or pasted conversation transcript should be required.