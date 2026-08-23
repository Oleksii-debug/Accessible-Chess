# NEXT_WAVE_DIRECTIVES

DIRECTIVE_ID: DEV5-1347
REVISION: 1
SOURCE_RUN: 20260823-1347
EFFECTIVE: next worker/DEV5 invocation after 2026-08-23 13:47:22 Europe/Uzhgorod cutoff.

1. SUPERSEDES DEV5-1301 promotion language. Do not treat `df52aeb3d99f4ae3d0089eab2882fe9b3c373dfd` as accepted/promoted Stage1 authority. Independent PR #158 proved that exact repair still leaked path-bearing `OSError.strerror`.
2. Prior accepted Stage1 baseline remains `0fa442330bc2bb03636ff9297512da4c29e38684` pending independent acceptance of a repaired successor.
3. Current DEV5 Stage1 repair candidate is exact PR #151 head `80720e8125c59a213f278668d599040f2768d553`.
4. DEV4 RUN_STATE `20260823-1300-stage1-oserror-strerror-privacy-proof` explicitly returned the minimal repair to DEV5 and requires independent exact-head revalidation after repair.
5. Exact DEV5 repair run `32634572205` is terminal SUCCESS. Linux `97182279775`: current external privacy oracles 13/13 including unchanged PR #158, selected PGN privacy 2/2, drive-relative oracle PASS, unittest 663/663, pytest 741 + 758 subtests, diagnostic PASS. Windows `97182279877`: privacy 10/10, Stage1 release contracts 75/75, unittest 663/663, pytest 741 + 758 subtests, diagnostic PASS.
6. Repair semantics: no arbitrary `OSError.strerror` crosses the ImportRegistry user-facing batch boundary. Stable filesystem context, errno when available and report-safe filename fields remain; internal verification and exception causes remain available.
7. No chess-state, GameTree, UI/WebView, ACSDB, Teacher/Classroom, strict packaged UIA helper or frozen ref mutation is part of `80720e8...`.
8. NEXT OWNER: independent DEV4/AUDIT must revalidate exact `80720e8...`, PR #151 diff and run `32634572205`. DEV5 must not label its own evidence independent.
9. If independent acceptance is GREEN, DEV5 may establish/designate the new repaired Stage1 authority. Do not merge PR #151 merely for convenience and do not rewrite the historical `0fa442...` baseline.
10. Only after that acceptance create/designate exactly one fresh Windows candidate harness locked to the accepted repaired Product SHA. Old PR #139, stale V3 locks and rejected ZIP are forbidden as candidate authority.
11. Candidate chain must be uninterrupted GREEN through source identity, frozen-core identity, release contracts, WAV, official Stockfish, native menu, Nuitka EXE, built-EXE diagnostic, real WebView2, strict packaged UIA, packaged sound/Stockfish lifecycle, release preflight, ZIP reopen/identity and artifact upload.
12. UIA remains C / INCONCLUSIVE: native Backspace delivery is proven; the observed failure occurs during QA SetValue restore before Ctrl+A. No Ctrl+A/C Product defect is proven.
13. Do not patch Product selection/clipboard based on a pre-Ctrl+A synchronization failure. QA observability fixes must preserve exact element identity and strict native-key assertions.
14. `FRESH_WINDOWS_CANDIDATE=NO`, `READY_FOR_RELEASE=NO`, `NVDA_VERIFIED=NO` until exact evidence changes them.
15. Persistent Full Product authority stays `dd9ebf9414103c805892856fe6a04706fa69039f` during Stage1 release freeze.
16. Do not duplicate post-cutoff touching work. Re-read live Drive/GitHub first on every continuation.
17. No force-push shared history, skips, xfails or weakened assertions.
