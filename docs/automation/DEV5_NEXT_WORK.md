# DEV5_NEXT_WORK

SOURCE_RUN: 20260823-1701
MODE: WAIT_FOR_D05_239_SELECTIVE_INTAKE / THEN_REAUDIT / THEN_ONE_FRESH_WINDOWS_CHAIN

1. Immutable coordination cutoff is `2026-08-23T14:01:47Z`. On the next invocation establish a new cutoff before using newer worker evidence.
2. Do not promote or create a candidate from D05 PR #222 head `88578e05eb0ea51795570f92f76428b9e029c11d`; it is superseded despite dual-OS GREEN run `32641454103`.
3. D04 PR #239 exact `53791a44176627b012f72c3ac5b7720214194975` is terminal and Audit-A accepted for selective Stage1 intake. Required cumulative preflight blob is `9213efc03e78756ec7d45f5983c91414b614b06f`; required regression blob is `4dec7df9ae945812d0cffacb168c912a7b8f56fb`.
4. Preserve #239 fail-closed bounds before `ZipFile.testzip()`: archive <=8 MiB, entries <=4096, one uncompressed member <=16 MiB, total uncompressed <=64 MiB. Preserve all earlier #218/#228 traversal/symlink/root/GPL/Win32/duplicate/casefold checks.
5. Existing D05 promotion surface owns the intake. If it is still being changed at the next cutoff, remain SAFE OVERLAP and do not create a competing Product branch.
6. After D05 publishes a newer exact head, inspect the selective diff. It must preserve accepted Stockfish resolver privacy, history fail-closed, FEN fail-closed, packaged submit-focus listener rebind, D03 hard kill/reap lifecycle, and D04 #218/#228 behavior while adding only #239 Product/test delta plus deliberate validation-lock updates.
7. Require one exact combined Ubuntu+Windows validation on the NEW recomposed SHA. Gate must include #218/#228/#239 D04 regressions; D03 hard-shutdown lifecycle; immutable PR159 privacy, PR193 FEN, PR196 focus oracles; release/accessibility contracts; full unittest; full pytest; SELFTEST; complete diagnostic; exact ancestry/blob/scope locks.
8. Require fresh exact-SHA AUDIT-A/B acceptance of that NEW SHA. Historical acceptance of `74f39ed...`, `53a0d7e...`, `fb8dfc3...`, or `88578e05...` does not authorize promotion.
9. Only after exact acceptance may shared `manual5/integration-20260821` fast-forward with `force=false` to that exact SHA.
10. Only then start exactly one WIP=1 fresh Windows candidate chain. Never reuse V5 or any rejected ZIP.
11. Fresh machine chain must prove source identity, release contracts, real WAV, official Stockfish lifecycle, native menu, Nuitka EXE, WebView2, strict packaged UIA including original Move Edit Backspace/Ctrl+A/Ctrl+C and post-submit semantic board focus, release preflight, ZIP reopen/hash/manifest/artifact identity.
12. `NVDA_VERIFIED` remains NO until the user personally tests that exact machine-GREEN candidate.
13. Do not merge PR #54 or frozen references for convenience; no force-push, skip, xfail, assertion weakening, or duplicate Product implementation.

FRESH_WINDOWS_CANDIDATE=NO
READY_FOR_RELEASE=NO
NVDA_VERIFIED=NO
