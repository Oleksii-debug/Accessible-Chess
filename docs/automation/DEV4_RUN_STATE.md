# DEV4 RUN STATE

RUN_ID: 20260822-2300-full-product-qa
STATUS: COMPLETE_WITH_TWO_PROVEN_PRODUCT_DEFECTS_IN_SAFE_OVERLAP
MODE: SAFE_OVERLAP_QA_EVIDENCE
ROLE: DEV4 independent QA/evidence/security
DIRECTIVE: AUDIT-20260822-1900-01 + DEV5-0028 coordination context
NVDA_VERIFIED=NO

## Exact live state

- Product under test: `full5/dev4-import-security-repair-20260822@6298899cb112336ef220caa8d0e52334ddc0c0ae`.
- Product PR #100 remains separate; no Product implementation was mutated in this QA run.
- QA evidence branch: `qa/dev4-postcommit-cleanup-evidence-20260822`.
- QA PR #127: OPEN/DRAFT/EVIDENCE-ONLY / DO NOT MERGE WHOLE BRANCH.
- Post-commit atomicity gate: `0190b9f19ba8a58cc3f809a87b06429c4699b1c8`.
- Cross-platform ChessBase path-privacy gate: `e99e242ea0b05eacd1fc9c03de93bbfa16c652ee`.
- QA workflow commit: `f8450e2469e434175489ad01942fd23721abbb81`.
- Exact focused QA run/job: `32595609798 / 97085913218` — FAILURE as expected evidence: 1 PASS, 2 FAIL.
- Exact QA head tested by that run: `ac6357957c474814a00405133f452bec73940bd3`.
- Local clean checkout was independently blocked by sandbox DNS (`github.com` cannot resolve): `QA_OR_ENVIRONMENT_ONLY`; hosted GitHub Actions supplied executable evidence instead.
- Windows strict WIP=1 untouched. No Ctrl+A/Ctrl+C Product claim.

## Independent DEV5 exact-Product validation

DEV5 validation PR #113 executed exact Product SHA `6298899cb112336ef220caa8d0e52334ddc0c0ae`.
Run/job: `32595341745 / 97085248183` — overall FAILURE.

Before the full-suite failure, the exact DEV4 security surface passed:
- provenance/diff hygiene PASS;
- compile PASS;
- real `os.link` no-clobber race oracle PASS;
- DEV4-focused pytest: 37/37 PASS;
- expected-hash race unittest PASS;
- canonical DEV2 GameTree + corrected DEV4 QA race overlay: 11/11 PASS.

Full unittest then ran 645 tests and ended with 4 failures + 1 error; full pytest and diagnostic were skipped.

## PROVEN_PRODUCT_DEFECT 1 — cross-platform ChessBase report path privacy

`acs.chessbase_adapter._report_name()` returns `path.name`. On POSIX, Windows-formatted backslashes are ordinary filename characters. Exact QA run `32595609798` proved that `C:\Users\PrivateUser\Documents\Training Database.CBH` is serialized with `PrivateUser` and directory components intact instead of reducing to a report-safe identifier.

This violates the established DEV4 rule that serialized/user-facing ChessBase evidence must not expose workstation directories. DEV5 full-suite evidence independently exposed the related portability boundary through the Windows-path provenance regression.

Strict evidence: `tests/test_dev4_chessbase_cross_platform_path_privacy.py` at `e99e242...`.
Product code intentionally unchanged in this QA lane.

## PROVEN_PRODUCT_DEFECT 2 — no-clobber save can report failure after commit

`_publish_no_clobber()` first creates the destination atomically with `os.link(tmp_path, destination)` and only then removes the temporary pathname. Exact QA run `32595609798` injected an `OSError` from the post-link temp unlink. The destination already existed with the requested committed PGN, yet `save_pgn_atomic()` propagated an exception.

This creates a deterministic committed-but-reported-failed state. A caller may retry or report loss even though the destination is already published, breaking the save operation's atomic success/failure observability and retry semantics.

Strict evidence: `tests/test_dev4_pgn_postcommit_cleanup_atomicity.py` at `0190b9f...`.
The paired expected-hash CAS-snapshot cleanup test PASSED, so this finding is specifically localized to the no-clobber post-link temp-name cleanup path; do not generalize it to the CAS path.

Product code intentionally unchanged in this SAFE OVERLAP QA lane.

## Other classifications

- `QA_OR_ENVIRONMENT_ONLY / stale compatibility`: ACSDB full-suite expectation requiring raw exception detail conflicts with intentional persisted-error privacy redaction (`IntegrityError: import failed`). Never restore raw error leakage merely for GREEN.
- `INCONCLUSIVE contract tension`: old ChessBase provenance test expects parent directory `incoming/...`; richer provenance must not override the explicit report-path privacy boundary without a separate safe identifier contract.
- `QA_OR_ENVIRONMENT_ONLY / cross-lane`: GameTree semicolon-comment formatting is DEV2-owned; semantic comment content remains present.
- `INCONCLUSIVE / outside DEV4 ownership`: Stage1 native-menu test-double `dispatch_action` error.
- `HUMAN_ONLY`: exact fresh Windows/NVDA usability. `NVDA_VERIFIED=NO`.

## Next action

1. Route both proven findings to authorized DEV4 Product repair without competing with active Product/integration work.
2. Required minimal Product repair A: make ChessBase report identifiers path-syntax-neutral and privacy-safe for both slash conventions; never expose parent directories to serialized/user-facing reports.
3. Required minimal Product repair B: after successful no-clobber `os.link`, cleanup of the now-redundant temp name must not turn the committed save into a reported failure; preserve observability of cleanup problems without lying about commit state.
4. Re-run strict QA gates plus all existing DEV4-focused tests on the repaired Product head.
5. Continue non-overlapping path/error/privacy/import evidence while DEV3/DEV5 own active ACSDB/integration surfaces.
6. Stay out of strict Windows WIP=1, DEV5 integration, Stage1 release, and DEV2 canonical GameTree ownership.
