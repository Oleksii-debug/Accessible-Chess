# DEV4 SESSION HANDOFF

SESSION: 20260822-2300 Full Product independent QA/evidence/security
STATUS: COMPLETE_WITH_NEW_QA_EVIDENCE_AND_CROSS_LANE_CI_RED
MODE: SAFE_OVERLAP_QA_EVIDENCE
NVDA_VERIFIED=NO

## Exact state basis

- Product under test: `full5/dev4-import-security-repair-20260822@6298899cb112336ef220caa8d0e52334ddc0c0ae`.
- Product PR #100 was not mutated by this run.
- QA evidence branch: `qa/dev4-postcommit-cleanup-evidence-20260822`.
- QA PR #127 is DRAFT / EVIDENCE ONLY / DO NOT MERGE WHOLE BRANCH.
- Evidence commits: `0190b9f19ba8a58cc3f809a87b06429c4699b1c8`, `e99e242ea0b05eacd1fc9c03de93bbfa16c652ee`.
- Focused QA workflow commit: `f8450e2469e434175489ad01942fd23721abbb81`.
- Local clean-checkout execution failed before tests because the sandbox could not resolve `github.com`: `QA_OR_ENVIRONMENT_ONLY`.
- PR #127 exact-head Actions were absent at checkpoint: `INCONCLUSIVE`, not GREEN.
- Windows strict WIP=1 untouched. No Ctrl+A/Ctrl+C Product defect claim.

## Independent exact-Product CI consumed

DEV5 PR #113 validated exact DEV4 Product `6298899...` in run/job `32595341745 / 97085248183`.

Machine result:
- exact provenance/diff hygiene PASS;
- compile PASS;
- actual `os.link` no-clobber race oracle PASS;
- DEV4 focused tests 37/37 PASS;
- expected-hash race unittest PASS;
- DEV2 canonical GameTree + corrected DEV4 race overlay 11/11 PASS;
- full unittest: 645 tests, 4 failures + 1 error -> overall workflow FAILURE;
- full pytest and complete diagnostic skipped after the unittest failure.

## New proven finding

`PROVEN_PRODUCT_DEFECT` — cross-platform ChessBase report path privacy.

The Product privacy helper returns `Path.name`. This strips native-platform directories, but it does not parse foreign path syntax. On POSIX a Windows-formatted path retains backslashes inside the filename token, so a value like `C:\Users\PrivateUser\Documents\Training Database.CBH` can cross `ChessBaseSourceProbe.as_report_fields()` as the entire private path rather than a report-safe identifier. The new strict QA test at `e99e242...` locks the requirement that workstation directory/user components never survive serialized report output.

The independent DEV5 full-suite failure in `test_windows_data_release_regressions...` corroborated the portability boundary by observing an unnormalized backslash path in ChessBase provenance output.

Product fix is intentionally NOT performed in this SAFE OVERLAP QA lane. Auditor/Product owner should repair with a platform-neutral privacy-safe naming rule rather than re-exposing raw parent directories.

## Additional classifications

- `INCONCLUSIVE`: post-commit cleanup false-failure semantics. Gate `0190b9f...` models an exception after filesystem publication already succeeded; promote only after executable evidence and exact public contract review.
- `QA_OR_ENVIRONMENT_ONLY / stale compatibility`: old ACSDB test expects raw storage exception text, conflicting with the intentional persisted-error privacy redaction. Never restore raw error leakage only for GREEN.
- `INCONCLUSIVE contract tension`: old ChessBase provenance test expects `incoming/...`; richer provenance must not silently override the explicit report-path privacy requirement.
- `QA_OR_ENVIRONMENT_ONLY / cross-lane`: GameTree semicolon comment representation is DEV2-owned and semantic content remains serialized.
- `INCONCLUSIVE / outside DEV4 ownership`: Stage1 native-menu test-double failure.
- `HUMAN_ONLY`: fresh Windows/NVDA acceptance; `NVDA_VERIFIED=NO`.

## Next exact action

Recheck PR #127 exact-head QA workflow. If executable evidence confirms the Windows-style path leak, keep the defect PROVEN and route a minimal platform-neutral report-safe Product repair through the authorized DEV4 Product lane. If post-commit cleanup tests fail, first prove whether the API contract forbids a committed-but-reported-failed outcome before requesting Product mutation. Continue non-overlapping path/error/privacy/import evidence while DEV3/DEV5 own active ACSDB/integration surfaces.
