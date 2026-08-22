# NEXT_WAVE_DIRECTIVES

DIRECTIVE_ID: DEV5-0030
REVISION: 1
SOURCE_RUN: 20260822-2358
EFFECTIVE: next fresh worker/DEV5 invocation; AUDIT_MASTER `AUDIT-20260822-1900-01` remains authoritative where newer or explicitly scoped.

1. Establish a fresh immutable cutoff before Product mutation; never retroactively intake work terminalized after that cutoff.
2. Preserve Stage1 `manual5/integration-20260821 @ 0fa442330bc2bb03636ff9297512da4c29e38684` and persistent exact-GREEN DEV5 `full5/dev5-compose-1700-20260822 @ dd9ebf9414103c805892856fe6a04706fa69039f`, CI `32577600761 / 97042099941` SUCCESS.
3. DEV1 RUN `20260822-2249` remains coordination-IN_PROGRESS at this cutoff. Source `edc979e783942403049997874eb966592d3a67d8` is machine-green but is not intake authority until terminal same-run handoff/readback exists.
4. DEV2 RUN `20260822-2240` remains coordination-IN_PROGRESS. Later Product/validation commits exist; do not partially intake. Require the final terminal canonical head + exact CI.
5. DEV3 terminal Product/test ceiling advances to `d3773b5d23946a9fe1ff15a25c6d8010e3bd9500`, exact CI `32597620359 / 97090954799` SUCCESS. It is a descendant of prior `9c8a342e...` and contains bounded FEN/request hardening only in DEV3-owned engine/analysis surfaces plus regressions. READY_FOR_INTEGRATION=YES.
6. DEV4 Product `6298899cb112336ef220caa8d0e52334ddc0c0ae` is BLOCKED. QA PR #127 run `32595609798 / 97085913218` proves cross-platform Windows-path privacy leakage through host-dependent `Path.name` handling and committed-but-reported-failed no-clobber publication after successful `os.link` followed by temp unlink error.
7. DEV4 must repair both proven defects minimally. Path reporting must handle POSIX and Windows syntax independent of runner OS, preserve only safe relative provenance, and redact absolute workstation paths. No-clobber publication must have deterministic post-commit cleanup/retry semantics: after successful link publication, cleanup failure must not be surfaced as an ambiguous failed save.
8. Do not weaken strict QA gates or restore raw ACSDB exception leakage, obsolete GameTree brace-normalization expectations, or old Stage1 seams for GREEN.
9. Never whole-merge DEV4 PR #100/#127/#113. Preserve DEV2 `acs/gametree.py` and canonical domain. Reconcile DEV4 `acs/acsdb.py` hunk-level against current DEV3/current-green behavior.
10. While DEV1/DEV2 or another touching lane is active, SAFE OVERLAP only: exact CI/evidence review, conflict mapping, backlog ordering, disposable validation preparation and directive maintenance; no competing Product push.
11. After touching lanes are terminal and DEV4 repairs exact-green, create disposable selective composition from `dd9ebf...`: latest canonical DEV2 -> terminal DEV3 Product/test delta -> DEV4-owned import/PGN/ChessBase security delta -> latest terminal DEV1 presentation delta.
12. Run full PGN -> canonical GameTree -> ACSDB -> Unicode Search/Open plus malformed/resource/encoding/termination/concurrency/recovery/post-commit/path/privacy/provenance/Classroom/engine-bound/PresentationState/remote/Teacher/keyboard/focus/clipboard, full unittest, full pytest, SELFTEST, complete WebView2 diagnostic and exact-head CI.
13. Persistent full5 advances only after exact-SHA GREEN. Never weaken tests, skip or xfail for GREEN. PR #54/frozen refs stay protected. Old rejected ZIP forbidden. Fresh Windows candidate requires the complete machine release chain. `NVDA_VERIFIED=NO` until the user personally verifies that exact candidate.
