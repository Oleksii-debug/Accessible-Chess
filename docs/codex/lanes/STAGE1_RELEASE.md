# Codex lane — Stage1 Release / Integration

Owner: primary Codex release agent.

Start branch: `codex/stage1-release-20260821`.

Mission: restore the exact current saturation head to green, close all remaining machine-verifiable Stage1 release blockers, and advance the Windows packaged release chain without weakening tests or inventing a Product clipboard defect from inconclusive QA evidence.

This lane owns implementation files necessary for Stage1 release closure. Other Codex lanes should not edit the same files concurrently without explicit coordination.

At every durable checkpoint append/update this file with:
- UTC timestamp;
- exact branch/SHA;
- completed package;
- focused/full tests;
- CI run/job IDs;
- unresolved P0/P1/P2;
- Windows strict/candidate state;
- next executable action.

Never set `NVDA_VERIFIED=YES`; human acceptance belongs to Oleksii.