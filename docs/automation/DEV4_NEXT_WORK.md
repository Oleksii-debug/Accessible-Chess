# DEV4 NEXT WORK

NEXT_ACTION_ORDER:

1. Re-read live Product PR #100, QA PR #127 exact head/Actions, DEV5/integration state, canonical Drive handoff and RUN_STATE before any mutation.
2. Preserve SAFE OVERLAP while Product/integration owners are active. QA branch must remain evidence-only unless a later directive explicitly transfers Product ownership.
3. Consume QA PR #127 focused workflow first. CI absence is `INCONCLUSIVE`, never GREEN.
4. Highest proven DEV4 QA finding: cross-platform ChessBase report-path privacy. Current `_report_name(path) -> path.name` is unsafe for Windows-style path strings processed on POSIX because backslashes are not separators there. Preserve strict gate `tests/test_dev4_chessbase_cross_platform_path_privacy.py` and require a platform-neutral report-safe identifier without workstation directories.
5. Do not “fix” the privacy finding by restoring raw/portable parent directory provenance. The established user-facing/report privacy boundary remains authoritative. If provenance needs richer identity, define an opaque/report-safe identifier rather than exposing local directories.
6. Recheck the post-commit cleanup gate. If destination publication succeeds but temp/CAS-name cleanup raises, classify only after proving the public save contract and retry/data-loss consequence. Keep `INCONCLUSIVE` until then.
7. Preserve all earlier DEV4 Product security repairs and strict gates: symlink/reparse/special-file rejection, bounded PGN reads, stable fingerprints, ChessBase I/O observability, ACSDB error redaction, lossy-encoding quality downgrade, batch continuation, PGN path indirection rejection, no-clobber publication, expected-hash recovery, and recovery-snapshot preservation on rollback/verification failure.
8. Treat the DEV5 full-unittest ACSDB raw-error failure as stale compatibility evidence unless a privacy-safe observability contract proves otherwise; never reintroduce raw parser/storage exception text merely to make the old test green.
9. Keep GameTree comment representation/missing-termination semantics in DEV2 ownership. Preserve QA evidence but do not mutate canonical GameTree from this lane.
10. Keep Stage1 native-menu/test-double failures outside DEV4 unless a security/package boundary is concretely implicated.
11. Avoid shared `acs/acsdb.py` Product mutation while DEV3 schema/search work is semantically overlapping under DEV5-0028; continue read-only evidence/sink tracing instead.
12. Windows strict WIP=1. Do not take it over. No Ctrl+A/Ctrl+C Product claim without exact proof. `NVDA_VERIFIED=NO`.

CURRENT QA BRANCH: `qa/dev4-postcommit-cleanup-evidence-20260822`
CURRENT QA PR: #127
KNOWN EVIDENCE COMMITS:
- `0190b9f19ba8a58cc3f809a87b06429c4699b1c8` — post-commit cleanup ambiguity gate.
- `e99e242ea0b05eacd1fc9c03de93bbfa16c652ee` — cross-platform ChessBase path-privacy gate.
- `f8450e2469e434175489ad01942fd23721abbb81` — focused Ubuntu QA workflow.

DEV5 EXACT PRODUCT VALIDATION: run/job `32595341745 / 97085248183`; focused DEV4 gates PASS, overall full-suite RED due mixed compatibility/cross-lane failures. Do not summarize this run as either globally GREEN or as proof all failures are DEV4 Product defects.
