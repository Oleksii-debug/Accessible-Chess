# Accessible Chess — Codex autonomous session map

This repository is being handed to Codex temporarily for a high-throughput autonomous engineering session. The user is blind and relies on NVDA. Accessibility is a release-critical engineering requirement, not a documentation preference.

## Start here

Before changing code, read in this order:
1. `docs/codex/CURRENT_STATE.md`
2. `docs/codex/NEXT_WORK.md`
3. `docs/codex/ACCEPTANCE.md`
4. `docs/codex/RECOVERY.md`
5. `docs/CANONICAL_PRODUCT_VISION_UA.md`
6. `docs/TECHNICAL_ROADMAP.md`
7. Live GitHub Issues #14, #22 and #45, PR #54, current branches, Actions and artifacts.

GitHub live technical evidence wins over stale status prose. Never assume a green state from an older handoff when a newer exact SHA or workflow exists.

## Mission

Advance Accessible Chess as far toward the complete canonical Windows product as safely possible during the available Codex session. Work hardest and highest-value blockers first. Do not stop after the first fix. After each coherent verified package, checkpoint and continue to the next READY package until a real external blocker, a human-only decision, or the session/usage limit stops work.

## Release and accessibility invariants

- Windows is the product platform.
- One canonical chess core remains the source of truth.
- Keyboard/NVDA and mouse/visual paths must converge on the same application commands/state.
- A feature is incomplete if it is mouse-only.
- Move Input, Position Editor, Teacher Pointer, Annotation and Student Hover/Selection are distinct command families.
- Never claim human NVDA verification. `NVDA_VERIFIED=NO` until Oleksii personally accepts the exact fresh Windows candidate.
- The old human-rejected ZIP is forbidden.
- Do not weaken tests, accessibility semantics, release checks or security to make CI green.
- Never expose secrets, local paths, Python tracebacks or provider internals in user-facing UI.

## Stage1 release isolation

The frozen release lineage remains authoritative until a replacement is independently proven. Do not silently overwrite the frozen integration/candidate branches. Work on persistent Codex branches/worktrees. A Stage1 Product change must be fully tested before proposing integration.

If all machine-verifiable Stage1 work becomes green and the only remaining gate is human NVDA acceptance, do not idle. Continue the canonical roadmap in an isolated future-work branch/worktree without merging future-stage features into the frozen Stage1 release lineage.

## Git discipline

- Never force-push shared history.
- Never delete release branches/tags/artifacts to make the state look clean.
- Commit and push after every coherent atomic result or roughly every 10–15 minutes of valuable work, whichever comes first.
- Before risky refactors/migrations, push a safe checkpoint first.
- Use descriptive commit messages and exact SHAs in status updates.
- Keep independent work in independent branches/worktrees.
- Prefer small integration surfaces and evidence-rich commits over giant unreviewable rewrites.

## Verification discipline

At minimum for relevant Product changes:
- `git diff --check`
- `python -m compileall -q acs tests run_accessible_chess.py`
- `node --check` for affected JavaScript
- focused tests for the changed subsystem
- full `python -m unittest discover -s tests -v`
- full `python -m pytest -q`
- `python run_accessible_chess.py --diagnostic`
- applicable GitHub Actions / Windows packaged gates

For changes that touch release composition, WebView2, UIA, native menu, sounds, Stockfish or packaging, add/retain exact regression evidence rather than relying only on unit tests.

## Autonomous execution rule

Use the largest safe coherent package you can complete and verify. Prefer fixing root causes and closing requirement clusters over one-line symptom patches. Use parallel agents/worktrees when available only for independent file/ownership domains. If parallel delegation is unavailable, execute the same lanes sequentially.

When blocked, record the exact blocker and immediately move to the highest-priority independent READY package. Do not wait for the user unless the next action truly requires a human decision or human-only NVDA observation.

Before the session ends, update `docs/codex/CURRENT_STATE.md` and `docs/codex/NEXT_WORK.md` with exact branch/SHA/tests/failures/remaining work so the manual Developer/Auditor chats can resume without reconstructing context.