# NEXT_WAVE_DIRECTIVES

DIRECTIVE_ID: DEV5-1356
REVISION: 1
SOURCE_RUN: 20260823-1356
EFFECTIVE: next worker/DEV5 invocation after 2026-08-23T10:55:53Z cutoff.

1. Current integration `manual5/integration-20260821@80720e8125c59a213f278668d599040f2768d553` is RELEASE_HOLD, not candidate authority.
2. Independent QA PR #159, head `66d5affbe027a86717a775198ec9fbcf8aba8545`, run `32634729467`, proves the release-critical Product defect: existing Stockfish runtime 18/18 PASS; focused resolver path-privacy oracle 3/3 FAIL on Ubuntu and Windows. Missing configured, missing packaged and empty/corrupt executable diagnostics leak private parent paths.
3. Preserve already-merged PR #151 history. Do not force-rewrite integration; repair by a minimal appended Product delta.
4. At this cutoff touching DEV4 PR #162 already owned the same `acs/stockfish_runtime.py` hot file. No corrected terminal validation became eligible since the prior 10:55:02Z snapshot. SAFE OVERLAP remains mandatory; do not create a competing Product repair.
5. Post-cutoff DEV4/DEV5 repair branches and CI are quarantine only for this directive. Re-evaluate them under the next fresh cutoff before intake.
6. NEXT WAVE FIRST ACTION: inspect exact current touching repair heads, underlying Product commit(s), ancestry, changed files, workflow runs/jobs/logs and terminal status. Identify one coherent terminal repair lineage rooted at `80720e8...`.
7. Required semantics: report-facing `resolve_stockfish_path()` diagnostics retain only safe executable-name/report provenance and never private parent directories or raw untrusted resolution exception text; typed errors, actual resolved Path, configured-path authority, packaged-relative layout, provider identity, retry/close and UCI lifecycle remain unchanged.
8. Promotion requires corrected exact GREEN evidence for ancestry/diff hygiene; existing Stockfish runtime; byte-unchanged PR #159 oracle; current `tests/test_stage1_release_path_privacy.py`; complete focused privacy/release suite; full unittest; full pytest; SELFTEST; complete diagnostic; Linux/Windows as applicable.
9. A RED caused only by stale CI inventory may be classified QA-only only after logs prove the Product/focused oracle passed, but it never substitutes for a corrected terminal GREEN promotion run.
10. If touching work remains active at the next cutoff, stay SAFE OVERLAP. If terminal and exact-GREEN, selectively append only the minimal Product delta; never merge QA/validation topology wholesale.
11. Require independent AUDIT_MASTER acceptance of the exact repaired Stage1 SHA before any user-candidate authority is established.
12. PR #160/V4 and any archive locked to defective `80720e8...` remain stale/forbidden. Do not reuse or relabel them.
13. Only after accepted repaired authority exists may exactly one fresh WIP=1 Windows candidate chain run: source/frozen identity → release contracts → WAV → official Stockfish → native menu → Nuitka → built EXE diagnostic → real WebView2 → strict packaged UIA → packaged sound/Stockfish lifecycle → release preflight → ZIP reopen/hash/identity → artifact upload.
14. Move Edit ValuePattern/SetValue/Ctrl+A/Ctrl+C remains a separate QA-owned `C — INCONCLUSIVE` track. Do not patch Product clipboard/selection without B-class evidence.
15. Persistent Full Product authority remains `dd9ebf9414103c805892856fe6a04706fa69039f` during Stage1 release freeze.
16. `FRESH_WINDOWS_CANDIDATE=NO`, `READY_FOR_RELEASE=NO`, `NVDA_VERIFIED=NO` until exact evidence changes them.
17. Old rejected ZIP, PR #54 and frozen refs remain untouched.
18. No force-push, skips, xfails, test weakening or duplicate touching implementations.
