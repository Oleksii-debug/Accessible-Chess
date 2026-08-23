# NEXT_WAVE_DIRECTIVES

DIRECTIVE_ID: DEV5-1701
REVISION: 1
SOURCE_RUN: 20260823-1701
EFFECTIVE: next worker/DEV5 invocation after `2026-08-23T14:01:47Z` cutoff.

1. Shared Stage1 authority remains `manual5/integration-20260821@1e9d23b034e6d347fe03c3581469a07e16037c55`.
2. Active D05 promotion surface is PR #222. Exact head `88578e05eb0ea51795570f92f76428b9e029c11d` is dual-OS GREEN on run `32641454103` but is SUPERSEDED as final audit/promotion target by newer terminal D04 PR #239.
3. D04 #239 exact head is `53791a44176627b012f72c3ac5b7720214194975`; required cumulative `acs/release_preflight.py` blob is `9213efc03e78756ec7d45f5983c91414b614b06f`; regression blob is `4dec7df9ae945812d0cffacb168c912a7b8f56fb`.
4. #239 red-first run `32641610135` proves the old preflight lacked fail-closed resource bounds before Stockfish source ZIP CRC/decompression. Final run `32641696408` is terminal SUCCESS on Ubuntu `97199654044` and Windows `97199654106` with focused/prior D04, full suites, SELFTEST and diagnostic GREEN.
5. Preserve exact #239 limits before `ZipFile.testzip()`: archive <=8 MiB, entries <=4096, single uncompressed member <=16 MiB, total uncompressed <=64 MiB. Preserve all earlier #218/#228 security/canonicality checks.
6. AUDIT-A has independently accepted #239 for selective Stage1 intake and explicitly invalidated `88578e05...` as final source-promotion target pending recomposition.
7. D05/PR #222 owns the touching intake. Other workers must use SAFE OVERLAP while that promotion surface is active: no competing Product push to `acs/release_preflight.py`, no alternate Stage1 promotion branch, no candidate build.
8. D05 selective intake must preserve prior accepted Stage1 Product identities: Stockfish resolver privacy, history scalar fail-closed, oversized FEN fail-closed, packaged submit-focus listener rebind, and D03 hard kill/reap lifecycle. No wholesale D04 workflow intake is required.
9. The next recomposed exact head must run one combined Ubuntu+Windows gate with exact ancestry/blob/scope locks; #218/#228/#239 D04 regressions; D03 lifecycle; immutable PR159 privacy, PR193 FEN, PR196 focus oracles; focused release/accessibility; full unittest; full pytest; SELFTEST; complete WebView2 diagnostic.
10. Historical audit acceptances of `74f39ed...`, `53a0d7e...`, `fb8dfc3...`, or `88578e05...` do not authorize the new SHA. Fresh exact-SHA Audit-A/B acceptance is mandatory.
11. Only after exact acceptance may `manual5/integration-20260821` fast-forward with `force=false` to the new SHA. No force-push.
12. Only after promotion may exactly one WIP=1 fresh Windows candidate chain begin. V5 and every old/rejected ZIP remain forbidden.
13. Fresh candidate must prove exact source identity, release contracts, real WAV, official Stockfish lifecycle, native menu, Nuitka EXE, real WebView2, strict packaged original Move Edit Backspace/Ctrl+A/Ctrl+C plus semantic board-focus continuity, preflight, ZIP reopen/hash/manifest/artifact identity.
14. `NVDA_VERIFIED` remains NO until the user personally verifies that exact candidate.
15. PR #54 and frozen references remain untouched. No skip/xfail/assertion weakening or CI topology manipulation to manufacture GREEN.

FRESH_WINDOWS_CANDIDATE=NO
READY_FOR_RELEASE=NO
NVDA_VERIFIED=NO
