# DEV5_NEXT_WORK

SOURCE_RUN: 20260823-1355
MODE: SAFE_OVERLAP / TERMINAL_DEV4_REPAIR_REVALIDATION_NEXT

1. Do not treat `80720e8125c59a213f278668d599040f2768d553` as release-acceptable merely because PR #151 CI was GREEN. PR #159 later proved an additional release-critical Product path leak on that exact SHA.
2. Do not rewrite the already-merged PR #151 history. The correct next repair is an appended minimal Stockfish runtime privacy delta.
3. At the next fresh cutoff, re-read canonical DEV4 handoff/RUN_STATE and live PR #162 before any Product write. This run could not intake it because the touching repair existed and was active at the 13:55:02 cutoff.
4. Identify the exact terminal Product commit beneath PR #162 and prove its parent is `80720e8...`; inspect the diff rather than merging the validation PR wholesale.
5. Required repair semantics: user/report-facing `resolve_stockfish_path()` diagnostics may retain the safe executable basename but must not expose private parent directories or raw resolution exception text. Preserve typed errors, actual resolved Path return, explicit configured-path authority, packaged-relative layout, provider identity, retry/close and UCI lifecycle semantics.
6. Required machine validation on exact terminal repair: ancestry/diff hygiene; existing Stockfish runtime regressions; byte-unchanged PR #159 3-case oracle; current `tests/test_stage1_release_path_privacy.py`; complete current privacy/release focused suite; full unittest; full pytest; SELFTEST; complete WebView2 diagnostic on Linux and Windows where applicable.
7. Ignore RED caused solely by stale validation inventory only after exact logs prove the Product/focused oracle passed; still require a corrected terminal GREEN run before promotion.
8. If DEV4 remains active/touching at the next cutoff, remain SAFE OVERLAP and do not compete.
9. If DEV4 is terminal pre-cutoff and exact GREEN, selectively append only the required Product delta to current Stage1 integration; never merge evidence/CI topology wholesale.
10. Obtain independent AUDIT_MASTER acceptance of the repaired exact Product SHA before any user candidate authority is established.
11. PR #160/V4 is stale because it targets defective `80720e8...`; do not accept, reuse or relabel any archive produced from that Product SHA.
12. After Audit accepts the repaired successor, create/designate exactly one fresh WIP=1 Windows candidate chain locked to that exact Product. Run source identity, release contracts, WAV, official Stockfish, native menu, Nuitka EXE, built-EXE diagnostic, real WebView2, strict UIA, packaged sound/Stockfish lifecycle, release preflight, ZIP reopen/hash/identity and artifact upload.
13. The Move Edit ValuePattern/SetValue/Ctrl+A/Ctrl+C track remains QA-owned C / INCONCLUSIVE. Do not mix speculative Product keyboard changes into the proven privacy repair.
14. `FRESH_WINDOWS_CANDIDATE=NO`, `READY_FOR_RELEASE=NO`, `NVDA_VERIFIED=NO` until exact evidence changes them.
15. Persistent Full Product authority remains `dd9ebf9414103c805892856fe6a04706fa69039f` during Stage1 release freeze.
16. No force-push, skips, xfails, test weakening or duplicate touching Product branch.
