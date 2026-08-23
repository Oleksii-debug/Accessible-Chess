# DEV5_NEXT_WORK

SOURCE_RUN: 20260823-2257
MODE: WAIT_FOR_S1_01_D04_DUPLICATE_KEY_REPAIR / THEN_S1_02_RECOMPOSE / THEN_REAUDIT / THEN_ONE_FRESH_WINDOWS_CHAIN

1. Coordination cutoff for this run is `2026-08-23T19:57:48Z`. On the next invocation establish a fresh cutoff before using newer worker evidence.
2. Shared Stage1 authority remains `manual5/integration-20260821@1e9d23b034e6d347fe03c3581469a07e16037c55`; do not move it.
3. D05 PR #222 exact `88578e05eb0ea51795570f92f76428b9e029c11d` is superseded and cannot be promoted.
4. D04 #239 exact `53791a44176627b012f72c3ac5b7720214194975` preserves accepted #218/#228/#239 semantics but is not final-intake safe because #249 proves `PROVEN_PRODUCT_DEFECT / P1 / RELEASE_EVIDENCE_JSON_CANONICALITY` on that exact parent.
5. S1-01 alone owns Product repair of #249. Required behavior: central release JSON parsing rejects duplicate object keys at every nesting level before semantic validation; malformed/unreadable containment and valid release semantics remain unchanged; #249 oracle remains unchanged.
6. No terminal S1-01/D04 repair exists at this cutoff. Remain SAFE OVERLAP: no DEV5 Product patch to `acs/release_preflight.py`, no #239 final intake, no authority move, no candidate build.
7. When a repair becomes admissible at a future cutoff, require exact Linux+Windows owner evidence: unchanged #249 oracle GREEN, cumulative #218/#228/#239 regressions GREEN, full unittest, full pytest, SELFTEST, complete diagnostic, exact ancestry/scope/blob locks.
8. S1-02/D05 then selectively recomposes only accepted Product/test deltas onto the current Stage1 graph, preserving accepted Stockfish resolver privacy, history and FEN fail-closed behavior, packaged submit-focus listener rebind, D03 hard kill/reap lifecycle, and all release-preflight security semantics. Do not wholesale merge evidence workflows.
9. Require one NEW exact combined Ubuntu+Windows gate replaying #218/#228/#239/#249, D03 lifecycle, immutable PR159 privacy, PR193 FEN and PR196 focus oracles, release/accessibility contracts, full unittest/pytest, SELFTEST, complete diagnostic and exact provenance locks.
10. Require fresh exact-SHA AUDIT-A/B acceptance. Historical acceptance of earlier SHAs cannot authorize promotion.
11. Only after exact acceptance may shared authority fast-forward with `force=false`.
12. Only then may S1-05 start exactly one WIP=1 fresh Windows candidate chain. Never reuse V5 or any rejected ZIP.
13. Fresh chain must prove exact source identity, release contracts, real WAV, official Stockfish lifecycle, native menu, Nuitka EXE, WebView2, strict packaged UIA including original Move Edit Backspace/Ctrl+A/Ctrl+C and semantic post-submit board focus, release preflight, ZIP reopen/hash/manifest/artifact identity.
14. `NVDA_VERIFIED` remains NO until the user personally tests that exact machine-GREEN candidate.
15. Do not merge PR #54 or frozen references for convenience. No skip/xfail/assertion weakening and no CI-topology manipulation to manufacture GREEN.

AUTHORITY_PROMOTED=NO
FRESH_WINDOWS_CANDIDATE=NO
READY_FOR_RELEASE=NO
NVDA_VERIFIED=NO
