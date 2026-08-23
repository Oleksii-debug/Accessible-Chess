# DEV5_NEXT_WORK

SOURCE_RUN: 20260823-1356
MODE: SAFE_OVERLAP / TERMINAL_REPAIR_REVALIDATION_NEXT

1. Do not certify `80720e8125c59a213f278668d599040f2768d553`; PR #159 proves a release-critical Stockfish runtime path-privacy defect on that exact SHA.
2. Preserve already-merged PR #151 history. The repair must be an appended minimal Product delta, not a force-rewrite.
3. At the next fresh cutoff, re-read all touching DEV4/DEV5 repair branches and their exact runs before any Product write.
4. Identify one terminal repair Product commit rooted at `80720e8...`; inspect exact changed files and ancestry. Never merge validation/QA topology wholesale.
5. Required repair semantics: `resolve_stockfish_path()` diagnostics may expose only safe executable-name/report provenance, never private parent directories or raw untrusted resolution exception text. Preserve typed errors, actual resolved Path, configured-path authority, packaged-relative layout, provider identity, retry/close and UCI lifecycle semantics.
6. Required validation on exact terminal repair: ancestry/diff hygiene; existing Stockfish runtime regressions; byte-unchanged PR #159 3-case oracle; current `tests/test_stage1_release_path_privacy.py`; complete focused Stage1 privacy/release suite; full unittest; full pytest; SELFTEST; complete diagnostic; Linux/Windows as applicable.
7. CI failures attributable to validation topology may be classified as QA-only only when logs prove Product/focused oracles passed, but promotion still requires a corrected terminal GREEN run.
8. If any worker remains active/touching at the next cutoff, remain SAFE OVERLAP and do not compete.
9. If terminal pre-cutoff evidence is fully GREEN, selectively append only the required Product delta to current Stage1 integration history and obtain independent AUDIT_MASTER acceptance of the exact resulting SHA.
10. PR #160/V4 and any archive locked to defective `80720e8...` are stale and forbidden as candidate authority.
11. Only after accepted repair authority exists, create/designate exactly one fresh WIP=1 Windows candidate chain locked to that SHA: source/frozen identity, release contracts, WAV, official Stockfish, native menu, Nuitka, built EXE diagnostic, real WebView2, strict packaged UIA, packaged sound/Stockfish lifecycle, release preflight, ZIP reopen/hash/identity, artifact upload.
12. Move Edit ValuePattern/SetValue/Ctrl+A/Ctrl+C remains QA-owned `C — INCONCLUSIVE`; do not mix speculative keyboard/clipboard Product changes into the privacy repair.
13. `FRESH_WINDOWS_CANDIDATE=NO`, `READY_FOR_RELEASE=NO`, `NVDA_VERIFIED=NO` until exact evidence changes them.
14. Persistent Full Product authority remains `dd9ebf9414103c805892856fe6a04706fa69039f` during Stage1 release freeze.
15. Old rejected ZIP, PR #54 and frozen refs remain untouched.
16. No force-push, skips, xfails, test weakening or duplicate touching Product implementation.
