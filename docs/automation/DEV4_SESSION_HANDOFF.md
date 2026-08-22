# DEV4 SESSION HANDOFF

SESSION: 20260822-2300 Full Product independent QA/evidence/security
STATUS: COMPLETE_WITH_TWO_PROVEN_PRODUCT_DEFECTS_IN_SAFE_OVERLAP
MODE: SAFE_OVERLAP_QA_EVIDENCE
NVDA_VERIFIED=NO

## Exact state basis

- Product under test: `full5/dev4-import-security-repair-20260822@6298899cb112336ef220caa8d0e52334ddc0c0ae`.
- Product PR #100 was not mutated by this run.
- QA evidence branch: `qa/dev4-postcommit-cleanup-evidence-20260822`.
- QA PR #127 is DRAFT / EVIDENCE ONLY / DO NOT MERGE WHOLE BRANCH.
- Evidence commits: `0190b9f19ba8a58cc3f809a87b06429c4699b1c8`, `e99e242ea0b05eacd1fc9c03de93bbfa16c652ee`.
- Focused QA workflow commit: `f8450e2469e434175489ad01942fd23721abbb81`.
- Hosted focused run/job `32595609798 / 97085913218` tested exact QA head `ac6357957c474814a00405133f452bec73940bd3` and returned 1 PASS / 2 FAIL.
- Local clean-checkout execution independently failed before tests because the sandbox could not resolve `github.com`: `QA_OR_ENVIRONMENT_ONLY`; hosted Actions supplied the decisive evidence.
- Windows strict WIP=1 untouched. No Ctrl+A/Ctrl+C Product defect claim.

## Independent exact-Product CI consumed

DEV5 PR #113 validated exact DEV4 Product `6298899...` in run/job `32595341745 / 97085248183`.

Machine result before cross-lane full-suite RED:
- exact provenance/diff hygiene PASS;
- compile PASS;
- actual `os.link` no-clobber race oracle PASS;
- DEV4 focused tests 37/37 PASS;
- expected-hash race unittest PASS;
- DEV2 canonical GameTree + corrected DEV4 race overlay 11/11 PASS.

Full unittest then ran 645 tests and ended with 4 failures + 1 error; full pytest and complete diagnostic were skipped.

## PROVEN_PRODUCT_DEFECT 1 — cross-platform ChessBase report path privacy

The Product privacy helper returns `Path.name`, which only understands the host platform path syntax. Exact hosted QA proved that on POSIX a Windows-formatted value `C:\Users\PrivateUser\Documents\Training Database.CBH` crosses `ChessBaseSourceProbe.as_report_fields()` with `PrivateUser` and directory components still present. This leaks workstation path information into serialized/user-facing report evidence and violates the established DEV4 privacy contract.

Strict gate: `tests/test_dev4_chessbase_cross_platform_path_privacy.py` at `e99e242...`.

The DEV5 full-suite Windows-path provenance failure independently corroborates the same portability boundary. Product fix was intentionally not performed in this SAFE OVERLAP QA lane.

## PROVEN_PRODUCT_DEFECT 2 — no-clobber save can report failure after commit

The Product no-clobber publisher performs `os.link(tmp_path, destination)` before `tmp_path.unlink()`. Exact hosted QA injected an `OSError` only at that post-link temp cleanup. The destination already existed with the requested committed PGN, but `save_pgn_atomic()` propagated an exception. This is a deterministic committed-but-reported-failed state with ambiguous retry semantics.

Strict gate: `tests/test_dev4_pgn_postcommit_cleanup_atomicity.py` at `0190b9f...`.

The paired expected-hash CAS-snapshot cleanup test PASSED in the same run, so the finding is specifically localized to no-clobber post-link temp-name cleanup; do not overgeneralize it.

## Other classifications

- `QA_OR_ENVIRONMENT_ONLY / stale compatibility`: old ACSDB test expects raw storage exception text, conflicting with intentional persisted-error privacy redaction. Never restore raw error leakage only for GREEN.
- `INCONCLUSIVE contract tension`: old ChessBase provenance test expects `incoming/...`; richer provenance must not silently override report-path privacy without a separate safe identifier contract.
- `QA_OR_ENVIRONMENT_ONLY / cross-lane`: GameTree semicolon comment representation is DEV2-owned and semantic content remains serialized.
- `INCONCLUSIVE / outside DEV4 ownership`: Stage1 native-menu test-double failure.
- `HUMAN_ONLY`: fresh Windows/NVDA acceptance; `NVDA_VERIFIED=NO`.

## Next exact action

Route two minimal Product repairs through the authorized DEV4 Product lane when SAFE OVERLAP clears: (A) path-syntax-neutral report-safe ChessBase naming for both slash conventions, and (B) no-clobber post-link cleanup handling that cannot report publication failure after destination commit. Then re-run the two strict QA gates, existing DEV4 focused suite, cross-lane selective validation and exact-SHA CI. Continue non-overlapping path/error/privacy evidence meanwhile; do not enter DEV3 ACSDB, DEV5 integration, Stage1 release, DEV2 GameTree or strict Windows ownership.
