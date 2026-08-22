# DEV4 RUN STATE

RUN_ID: 20260822-2300-full-product-qa
STATUS: COMPLETE_WITH_NEW_QA_EVIDENCE_AND_CROSS_LANE_CI_RED
MODE: SAFE_OVERLAP_QA_EVIDENCE
ROLE: DEV4 independent QA/evidence/security
DIRECTIVE: AUDIT-20260822-1900-01 + DEV5-0028 coordination context
NVDA_VERIFIED=NO

## Exact live state

- Product under test: `full5/dev4-import-security-repair-20260822@6298899cb112336ef220caa8d0e52334ddc0c0ae`.
- Product PR #100 remains separate; no Product implementation was mutated in this QA run.
- QA evidence branch: `qa/dev4-postcommit-cleanup-evidence-20260822`.
- QA PR #127: OPEN/DRAFT/EVIDENCE-ONLY / DO NOT MERGE WHOLE BRANCH.
- Post-commit ambiguity gate: `0190b9f19ba8a58cc3f809a87b06429c4699b1c8`.
- Cross-platform ChessBase path-privacy gate: `e99e242ea0b05eacd1fc9c03de93bbfa16c652ee`.
- QA workflow commit: `f8450e2469e434175489ad01942fd23721abbb81`.
- Local clean checkout/focused execution is blocked by sandbox DNS (`github.com` cannot resolve): `QA_OR_ENVIRONMENT_ONLY`.
- Exact PR #127 Actions were not observable at this checkpoint: `INCONCLUSIVE`, never GREEN.
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

The full unittest phase then ran 645 tests and ended with 4 failures + 1 error; full pytest and diagnostic were skipped.

## Finding classifications

### PROVEN_PRODUCT_DEFECT — cross-platform ChessBase report path privacy

`acs.chessbase_adapter._report_name()` currently returns `path.name`. On POSIX, a Windows-formatted path such as `C:\Users\PrivateUser\Documents\Training Database.CBH` treats backslashes as ordinary filename characters, so `Path.name` can return the entire Windows-formatted private path. `ChessBaseSourceProbe.as_report_fields()` then serializes that value as `source_path`.

This violates the already-established DEV4 report-path privacy requirement and can expose workstation directory/user names when Windows-style path text is processed cross-platform. New strict gate: `tests/test_dev4_chessbase_cross_platform_path_privacy.py` at `e99e242...`.

DEV5 full-suite evidence independently exposed the same portability boundary: `test_windows_data_release_regressions...test_chessbase_provenance_uses_portable_forward_slashes` observed `incoming\\Training Database.CBH` rather than a normalized portable/report-safe representation.

Product code intentionally remains unchanged in this independent QA lane.

### INCONCLUSIVE — post-commit cleanup false-failure semantics

`tests/test_dev4_pgn_postcommit_cleanup_atomicity.py` gates two cases where the destination has already been committed but cleanup of a temporary/CAS name raises. An API exception after a successful filesystem commit can make retry semantics ambiguous, but this is not promoted to Product defect until executable evidence and the intended cleanup/reporting contract are established.

### QA_OR_ENVIRONMENT_ONLY / stale compatibility expectations

- ACSDB full-suite expectation requiring raw exception detail conflicts with the intentional persisted-error privacy redaction (`IntegrityError: import failed`). Do not revert privacy to satisfy the stale expectation.
- GameTree semicolon-comment formatting expectation is DEV2 canonical ownership and the serialized semantic comment remains present; no DEV4 defect claim.

### INCONCLUSIVE / outside DEV4 ownership

- Stage1 native-menu test-double `dispatch_action` error is an integration/Stage1 compatibility surface, not a DEV4 import/security Product claim from this run.
- The legacy ChessBase test expecting parent-directory provenance (`incoming/...`) exposes a contract tension between privacy and provenance granularity; do not invent a requirement. The separately proven defect is specifically cross-platform private-path leakage.

### HUMAN_ONLY

Exact fresh Windows/NVDA usability remains HUMAN_ONLY. `NVDA_VERIFIED=NO`.

## Next action

1. Recheck PR #127 exact-head QA workflow and consume its focused result if it appears.
2. Hand the proven cross-platform report-path privacy defect to the DEV4 Product owner/Audit without directly competing while Product/integration work is active.
3. If the post-commit cleanup gate executes RED, distinguish a true committed-but-reported-failed contract defect from harmless cleanup debris before any Product request.
4. Continue concrete path/error sink tracing and import/ACSDB security evidence that does not overlap active DEV3 schema/search work.
5. Stay out of strict Windows WIP=1, DEV5 integration, Stage1 release, and DEV2 canonical GameTree ownership.
