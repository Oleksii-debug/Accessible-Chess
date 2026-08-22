# DEV4 NEXT WORK

NEXT_ACTION_ORDER:

1. Re-read live Product PR #100, QA PR #127 exact head/Actions, DEV5/integration state, canonical Drive handoff and RUN_STATE before any mutation.
2. Preserve SAFE OVERLAP while Product/integration owners are active. QA branch remains evidence-only unless a later directive explicitly transfers Product ownership.
3. Two DEV4 Product defects are now machine-proven by focused run/job `32595609798 / 97085913218` on exact QA head derived from Product `6298899cb112336ef220caa8d0e52334ddc0c0ae`.
4. Product repair priority A — ChessBase cross-platform report-path privacy: replace platform-native-only `Path.name` report sanitization with path-syntax-neutral handling that strips both `/` and `\\` parent components. Do not restore raw parent directories merely to satisfy legacy provenance tests; if richer provenance is needed, use a separate opaque/report-safe identifier contract.
5. Product repair priority B — PGN no-clobber committed-but-reported-failed state: once `os.link(tmp_path, destination)` succeeds, failure to unlink the redundant temp pathname must not make the save API report that publication failed. Preserve cleanup observability without lying about commit state or making unsafe retries likely.
6. The paired expected-hash CAS snapshot cleanup test PASSED in the same focused run. Do not generalize the no-clobber defect to expected-hash publication.
7. Preserve all earlier DEV4 Product security repairs and strict gates: symlink/reparse/special-file rejection, bounded PGN reads, stable fingerprints, ChessBase I/O observability, ACSDB error redaction, lossy-encoding quality downgrade, batch continuation, PGN path-indirection rejection, no-clobber publication, expected-hash recovery, and recovery-snapshot preservation on rollback/verification failure.
8. Treat DEV5 full-unittest ACSDB raw-error failure as stale compatibility evidence unless a privacy-safe observability contract proves otherwise; never reintroduce raw parser/storage exception text merely for GREEN.
9. Keep GameTree comment representation/missing-termination semantics in DEV2 ownership. Preserve QA evidence but do not mutate canonical GameTree from this lane.
10. Keep Stage1 native-menu/test-double failures outside DEV4 unless a concrete security/package boundary is implicated.
11. Avoid shared `acs/acsdb.py` Product mutation while DEV3 schema/search work is semantically overlapping under DEV5-0028; continue read-only sink/error/privacy evidence instead.
12. After an authorized Product repair, run the two new strict tests first, then all existing DEV4-focused gates, cross-lane selective PGN/ChessBase checks, full unittest/pytest/diagnostic as applicable, and exact-SHA CI.
13. Windows strict WIP=1. Do not take it over. No Ctrl+A/Ctrl+C Product claim without exact proof. `NVDA_VERIFIED=NO`.

CURRENT QA BRANCH: `qa/dev4-postcommit-cleanup-evidence-20260822`
CURRENT QA PR: #127
EVIDENCE COMMITS:
- `0190b9f19ba8a58cc3f809a87b06429c4699b1c8` — no-clobber/expected-hash post-commit cleanup gates.
- `e99e242ea0b05eacd1fc9c03de93bbfa16c652ee` — cross-platform ChessBase path-privacy gate.
- `f8450e2469e434175489ad01942fd23721abbb81` — focused Ubuntu QA workflow.

FOCUSED QA RESULT: run/job `32595609798 / 97085913218` -> FAILURE with 1 PASS / 2 FAIL. Failures are the Windows-style private-path leak and no-clobber committed-but-reported-failed condition; expected-hash CAS cleanup gate passed.

DEV5 EXACT PRODUCT VALIDATION: run/job `32595341745 / 97085248183`; exact DEV4 focused gates PASS (37/37 plus race oracle and selective overlay 11/11), overall full-suite RED due mixed compatibility/cross-lane failures. Never summarize this as globally GREEN or claim every full-suite failure is a DEV4 defect.
