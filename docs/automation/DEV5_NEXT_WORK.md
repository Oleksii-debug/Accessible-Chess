# DEV5_NEXT_WORK

SOURCE_RUN: 20260823-2000
MODE: WAIT_FOR_D04_JSON_CANONICALITY_REPAIR / THEN_D05_RECOMPOSE / THEN_REAUDIT / THEN_ONE_FRESH_WINDOWS_CHAIN

1. Immutable coordination cutoff is `2026-08-23T16:59:32Z`. On the next invocation establish a fresh cutoff before using newer worker evidence.
2. Shared Stage1 authority remains `manual5/integration-20260821@1e9d23b034e6d347fe03c3581469a07e16037c55`. Do not move it now.
3. D05 PR #222 exact `88578e05eb0ea51795570f92f76428b9e029c11d` is superseded despite dual-OS GREEN run `32641454103`.
4. D04 #239 exact `53791a44176627b012f72c3ac5b7720214194975` is terminal GREEN for cumulative #218/#228/#239 release-preflight behavior, but it is NOT sufficient for final intake because exact #239 is proven vulnerable to duplicate JSON object keys.
5. D04 QA-only #249 exact `811ba1c8bb15aeb1241087822f45136e6ee537e8`, run `32647323503`, proves `PROVEN_PRODUCT_DEFECT / P1 / RELEASE_EVIDENCE_JSON_CANONICALITY`: existing D04 suites remain GREEN, while exactly two duplicate-key release-manifest cases fail on both Ubuntu and Windows.
6. Required D04 owner repair: central `_read_json_object()` path must reject duplicate object keys at every nesting level before semantic validation. Preserve malformed/unreadable error containment, exact valid JSON semantics, #218/#228 path/archive protections, and #239 source-ZIP resource bounds. Do not weaken or rewrite #249 oracle.
7. No terminal owner repair for #249 existed at this cutoff. Until one is terminal GREEN, remain SAFE OVERLAP: no competing DEV5 Product patch to `acs/release_preflight.py`, no #239 final intake, no Stage1 promotion, no candidate.
8. When D04 publishes a terminal repair, require exact owner evidence on Linux+Windows: unchanged #249 oracle GREEN, cumulative #218/#228/#239 regressions GREEN, full unittest, full pytest, SELFTEST, complete diagnostic, exact ancestry/scope/blob locks. Any post-cutoff repair must wait for the next DEV5 cutoff before coordination use.
9. After owner repair is admissible and accepted, D05 PR #222 must selectively intake the cumulative D04 Product/test delta through the newest repair, preserving accepted Stockfish resolver privacy, history scalar fail-closed, FEN fail-closed, packaged submit-focus listener rebind, and D03 hard kill/reap lifecycle. Do not wholesale merge D04 evidence workflows.
10. Require one NEW exact combined Ubuntu+Windows validation on the recomposed SHA with #218/#228/#239/#249 regressions; D03 hard-shutdown; immutable PR159 privacy, PR193 FEN, PR196 focus oracles; release/accessibility contracts; full unittest; full pytest; SELFTEST; complete diagnostic; exact ancestry/blob/scope/provenance locks.
11. Require fresh exact-SHA AUDIT-A/B acceptance of that NEW recomposed SHA. Historical acceptance of any earlier SHA does not authorize promotion.
12. Only after exact acceptance may `manual5/integration-20260821` fast-forward with `force=false`. No force-push.
13. Only then start exactly one WIP=1 fresh Windows candidate chain. Never reuse V5 or any rejected ZIP.
14. Fresh chain must prove exact source identity, release contracts, real WAV, official Stockfish lifecycle, native menu, Nuitka EXE, WebView2, strict packaged UIA including original Move Edit Backspace/Ctrl+A/Ctrl+C and semantic post-submit board focus, release preflight, ZIP reopen/hash/manifest/artifact identity.
15. `NVDA_VERIFIED` remains NO until the user personally tests that exact machine-GREEN candidate.
16. Do not merge PR #54 or frozen references for convenience. No skip/xfail/assertion weakening or CI topology manipulation to manufacture GREEN.

AUTHORITY_PROMOTED=NO
FRESH_WINDOWS_CANDIDATE=NO
READY_FOR_RELEASE=NO
NVDA_VERIFIED=NO
