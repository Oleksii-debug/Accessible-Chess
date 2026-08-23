# DEV3 NEXT WORK

Canonical Audit remains STAGE1 RELEASE FREEZE / FRESH WINDOWS CANDIDATE PRIORITY. Accepted Stage1 source authority remains `manual5/integration-20260821 @ 0fa442330bc2bb03636ff9297512da4c29e38684` until a repaired SHA is explicitly promoted.

Highest DEV3 priority on every continuation:
1. re-read DEV5 PR #151 and its exact head, workflow runs/jobs/logs. Current repair head `f99146f728ace6f76606beeea6caafbb6ac940e9` is Linux-full GREEN and Windows-privacy 6/6 GREEN, but Windows complete release CI is INCONCLUSIVE because checkout-time CRLF changes the working-tree hash seen by the frozen-core blob test;
2. require a CI-only line-ending materialization repair without weakening frozen SHA assertions: configure LF before rematerializing tracked files (for example reset/force checkout after `core.autocrlf=false` and `core.eol=lf`), then rerun the exact Windows job;
3. preserve DEV3 PR #150 accepted-source oracle unchanged. Current exact RED `32627037392 / 97163830449`: UCI recovery 3/3 PASS, engine-start privacy 2/2 FAIL on accepted `0fa44233...`;
4. preserve DEV3 PR #148 accepted-source PGN/ImportRegistry oracle unchanged. Current exact RED `32624495674 / 97157620475` proves the other accepted-Stage1 path leaks;
5. after PR #151 complete Linux + Windows validation is GREEN and Audit promotes a new accepted Stage1 SHA, replay the independent privacy oracles unchanged against that exact promoted authority before fresh-candidate certification;
6. only after privacy GREEN proceed through strict UIA, packaged Stockfish/sound lifecycle, release preflight, ZIP reopen/identity and artifact upload;
7. preserve DEV3 Windows runtime evidence `32600115025 / 97097006614` as supporting evidence only; it does not certify a candidate archive;
8. classify every RED before repair. Only a concrete Stockfish runtime, analysis, clock or engine-lifecycle defect may justify a DEV3 Product patch during freeze;
9. do not weaken privacy assertions, frozen-core SHA assertions or native Ctrl+A/Ctrl+C assertions for GREEN.

DEV5 owns the active release privacy repair. DEV3 must not implement a competing sanitizer, PGN/import repair or engine-start Product patch while that owner remains active.

Current terminal Full Product PR #137 remains technically GREEN for later selective DEV5 intake. Parallel DEV3 PR #134 remains terminal for final-review history identity and must not be duplicated.

Release success requires one fresh Windows archive from repaired exact accepted Stage1 source whose complete automated chain is GREEN and whose artifact identity is verified. Human NVDA verification comes only after that exact artifact is available.

SAFE_OVERLAP=YES
PROVEN_STAGE1_RELEASE_PRIVACY_DEFECT=YES
PROVEN_STAGE1_ENGINE_START_PRIVACY_DEFECT=YES
FRESH_WINDOWS_CANDIDATE=NO
NVDA_VERIFIED=NO
