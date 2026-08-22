# DEV5_NEXT_WORK

SOURCE_RUN: 20260822-2358
MODE: FRESH_CUTOFF_FIRST / SAFE_OVERLAP_OR_SELECTIVE_COMPOSE

1. Fresh immutable cutoff first; read canonical DEV1-DEV4 RUN_STATE/handoffs, PR heads and exact Actions.
2. Preserve Stage1 `0fa442330bc2bb03636ff9297512da4c29e38684` and persistent exact-GREEN DEV5 `dd9ebf9414103c805892856fe6a04706fa69039f` until superseded by exact-green selective composition.
3. If DEV1 Books/Training RUN `20260822-2249`, DEV2 Classroom/TeachingSession RUN `20260822-2240`, or any touching successor is still active, SAFE OVERLAP only.
4. DEV1: source `edc979e783942403049997874eb966592d3a67d8` has exact GREEN CI, but do not intake until canonical RUN_STATE/handoff terminalizes. Pre-terminal coordination ceiling remains `e358792a...`.
5. DEV2: later canonical Product evidence progressed beyond `8d9c7c99...`, but do not intake a partial active run. Require terminal same-run readback and exact CI before choosing the new ceiling.
6. DEV3 terminal Product/test ceiling is now `d3773b5d23946a9fe1ff15a25c6d8010e3bd9500`, CI `32597620359 / 97090954799` SUCCESS. Its 12-commit delta from `9c8a342e...` is limited to engine/analysis FEN and request resource-bound hardening plus tests/docs; consume Product/test commits selectively, not coordination history wholesale.
7. DEV4 `6298899c...` is BLOCKED by two proven defects from QA PR #127: cross-platform path privacy and post-link cleanup committed-but-reported-failed semantics. Require minimal Product repairs with strict regressions and exact focused/full GREEN before any intake.
8. DEV4 path repair must be syntax-neutral: relative POSIX/Windows provenance may remain portable and useful, but absolute workstation paths must never leak. Backslash inputs must be handled safely even on POSIX.
9. DEV4 no-clobber repair must establish one unambiguous contract after successful `os.link`: cleanup failure must not cause a false failure state that invites duplicate retry. Preserve destination bytes, fail-closed privacy, and deterministic recovery evidence.
10. Never whole-merge DEV4. Preserve DEV2 GameTree/domain. Reconcile DEV4 ACSDB hunk-level against accepted/current DEV3 semantics.
11. Once all touching lanes are terminal and DEV4 repairs are exact-green, create disposable selective composition from `dd9ebf...`: latest canonical DEV2 -> terminal DEV3 Product/test delta -> DEV4-owned import/PGN/ChessBase security delta -> latest terminal DEV1 presentation delta.
12. Combined gates: PGN open/save/publication -> canonical GameTree -> ACSDB -> Unicode Search/Open; malformed/oversized/invalid UTF-8/missing termination/truncation; expected-hash/no-clobber actual-primitive races; post-commit cleanup/retry semantics; symlink/reparse/FIFO/special-file rejection; cross-platform absolute-path privacy + relative provenance; batch continuation; Classroom corruption/privacy; bounded engine FEN/request surfaces; PresentationState/remote/Teacher invariants; keyboard/focus/clipboard; full unittest; full pytest; SELFTEST; complete WebView2 diagnostic; exact-head CI.
13. Persistent full5 advances only after exact-SHA GREEN. No test weakening/skips/xfail. PR #54/frozen refs protected. Rejected ZIP forbidden. Fresh Windows candidate only after complete machine release chain. `NVDA_VERIFIED=NO` until user verifies that exact candidate.
