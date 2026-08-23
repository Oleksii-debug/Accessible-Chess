# NEXT_WAVE_DIRECTIVES

DIRECTIVE_ID: DEV5-1503
REVISION: 1
SOURCE_RUN: 20260823-1503
EFFECTIVE: next worker/DEV5 invocation after 2026-08-23T12:03:00Z cutoff.

1. Accepted Stage1 at the 15:03 cutoff was `manual5/integration-20260821@1e9d23b034e6d347fe03c3581469a07e16037c55`, but it is not final release authority because pre-cutoff AUDIT_MASTER accepted separate history P1 repair `45956b38...` and proved a distinct oversized FEN-counter P1 routed to DEV2.
2. DEV5 draft PR #195 / branch `release/dev5-stage1-combined-repair-20260823` is the single controlled Stockfish+history combination surface. Do not create another duplicate combined Product line.
3. Exact PR #195 validation head `5e8ca72f7dd552ee151ebd5b85c52148004ac307` has terminal dedicated GREEN run `32638839597`: Ubuntu `97192655470`, Windows `97192655352`; repair 44/44; unchanged PR #159 3/3; stress 23 + 11; release 80/80; unittest 673/673; pytest 751 + 758; SELFTEST and diagnostic PASS.
4. This is INTERMEDIATE_COMBINED_GREEN only. PR #195 remains DRAFT / DO NOT MERGE OR PROMOTE. No V6 may be built from it while FEN P1 is absent.
5. DEV2 owns the oversized FEN-counter Product repair. On every continuation reread DEV2 RUN_STATE/handoff and live branch/PR before touching FEN files. If DEV2 is active at cutoff, all other workers use SAFE OVERLAP on that boundary.
6. A valid FEN repair must normalize conversion-time oversized digit-string `ValueError` to the existing concise FEN counter domain error, preserve atomic state, existing valid counter semantics and API containment, and add deterministic Board/API regressions. Do not add an arbitrary numeric cap unless accepted requirements explicitly demand one.
7. After terminal FEN repair, DEV5 selectively layers only Product/regression deltas onto the controlled combined Stage1 line; do not merge evidence/workflow PRs wholesale.
8. Final combined exact-tree validation must rerun Stockfish privacy, history fail-closed, FEN boundary, unchanged independent QA oracles, focused release/accessibility, full unittest, full pytest, SELFTEST and complete WebView2 diagnostic on Linux+Windows.
9. Independent AUDIT_MASTER acceptance is mandatory before designating/promoting the exact final combined Stage1 SHA.
10. V5 run `32636245736` is terminal RED, source obsolete, no ZIP. It did prove native Move Edit Ctrl+A selection and Ctrl+C clipboard copy; the historical clipboard/selection blocker is no longer open.
11. V5 submit-focus failure remains C / INCONCLUSIVE, not Product B. The retained helper used a pre-rerender UIA board target whose identity became stale/empty after board replacement. Require semantic square reacquisition on each bounded poll plus focus timeline before attributing a Product focus defect.
12. Post-cutoff submit-focus branches must be reread before any UI focus change. Do not duplicate touching Product/QA work.
13. Only after final Stage1 exact acceptance may DEV5 launch exactly one fresh WIP=1 Windows candidate chain locked to that SHA. No stale V5/V4 artifacts or old rejected ZIP may be reused.
14. Candidate must be uninterrupted GREEN through exact source/frozen identity, regressions/privacy, release contracts, WAV, official Stockfish, native menu, Nuitka EXE, real WebView2, strict packaged UIA, sound/Stockfish lifecycle, release preflight, ZIP reopen/hash/manifest identity and artifact upload.
15. `FRESH_WINDOWS_CANDIDATE=YES` is forbidden until exact machine artifact identity is verified. `NVDA_VERIFIED=NO` until Oleksii personally validates that exact candidate.
16. Persistent Full Product exact-GREEN authority remains `dd9ebf9414103c805892856fe6a04706fa69039f` during Stage1 release freeze.
17. PR #54, frozen refs and historical rejected ZIP remain untouched. No force-push, skip, xfail, assertion weakening or CI manipulation merely to obtain GREEN.
18. Post-cutoff evidence from the 15:03 wave never retroactively changes its intake decision; use a fresh immutable cutoff next time.

FRESH_WINDOWS_CANDIDATE=NO
READY_FOR_RELEASE=NO
NVDA_VERIFIED=NO
