# NEXT_WAVE_DIRECTIVES

DIRECTIVE_ID: DEV5-1355
REVISION: 1
SOURCE_RUN: 20260823-1355
EFFECTIVE: next worker/DEV5 invocation after 2026-08-23 13:55:02 Europe/Uzhgorod cutoff.

1. SUPERSEDES DEV5-1347 language that described `80720e8125c59a213f278668d599040f2768d553` as technically GREEN pending only independent acceptance. Independent PR #159 proves a new release-critical Product defect on that exact SHA.
2. PR #151 is already merged into `manual5/integration-20260821` at `80720e8...`. Preserve history; do not force-rewrite. Repair must be appended minimally.
3. PR #159 exact Product parent `80720e8...`, QA head `66d5affbe027a86717a775198ec9fbcf8aba8545`, run `32634729467`: existing Stockfish runtime 18/18 PASS; focused path-privacy oracle 3/3 FAIL on both Ubuntu and Windows. Missing configured, missing packaged and empty/corrupt executable diagnostics leak private parent paths.
4. AUDIT_MASTER classification is `PROVEN_PRODUCT_DEFECT / RELEASE-CRITICAL PRIVACY`. Intended Product repair uses canonical report-safe path rendering while preserving typed errors, executable resolution/configured-path authority, provider identity and lifecycle semantics.
5. At cutoff 10:55:02Z, touching DEV4 PR #162 already existed and was active on the same `acs/stockfish_runtime.py` hot file. Therefore run 1355 is SAFE OVERLAP; no DEV5 competing Product patch/intake is authorized from this run.
6. Post-cutoff observations are quarantine only. PR #162's narrow repair appears semantically aligned and its observed jobs pass existing runtime 18/18 plus unchanged PR #159 oracle 3/3. Observed full-validation RED is CI topology/inventory drift, including an obsolete `tests.test_stage1_path_privacy_repair` target. Do not call this terminal GREEN until a corrected exact run exists.
7. NEXT WAVE FIRST ACTION: re-read canonical DEV4 handoff/RUN_STATE, PR #162 exact current head/underlying Product commit, changed files and exact workflow runs. Determine whether repair was terminal before the new cutoff.
8. If still active/touching at new cutoff, remain SAFE OVERLAP. If terminal pre-cutoff, require exact GREEN validation for ancestry/diff hygiene; existing Stockfish runtime; unchanged PR #159; current `tests/test_stage1_release_path_privacy.py`; complete current privacy/release focused suite; full unittest; full pytest; SELFTEST; complete diagnostic.
9. Selectively append only the minimal terminal Product delta onto current Stage1 integration history. Never merge QA/validation topology wholesale.
10. Require independent AUDIT_MASTER acceptance of that exact repaired Product SHA before designating release authority.
11. PR #160/V4 and any artifact locked to defective `80720e8...` are stale and forbidden as candidate authority. Do not reuse or relabel them.
12. Only after Audit acceptance start exactly one fresh WIP=1 Windows candidate chain locked to the accepted repaired SHA: source/frozen identity, release contracts, WAV, official Stockfish, native menu, Nuitka, built EXE diagnostic, real WebView2, strict packaged UIA, packaged sound/Stockfish lifecycle, release preflight, ZIP reopen/hash/identity, artifact upload.
13. Move Edit ValuePattern/SetValue/Ctrl+A/Ctrl+C remains a separate QA-owned `C — INCONCLUSIVE` track. Do not patch Product clipboard/selection without B-class evidence.
14. `FRESH_WINDOWS_CANDIDATE=NO`, `READY_FOR_RELEASE=NO`, `NVDA_VERIFIED=NO` until exact evidence changes them.
15. Persistent Full Product authority remains `dd9ebf9414103c805892856fe6a04706fa69039f` during Stage1 release freeze.
16. Old human-rejected ZIP, PR #54 and frozen refs remain untouched.
17. No force-push, test weakening, skips, xfails or duplicate touching Product implementations.
