# DEV4 SESSION HANDOFF

SESSION: 20260823-0002 Full Product independent QA/evidence/security
STATUS: COMPLETE_WITH_TWO_PROVEN_PRODUCT_DEFECTS_IN_SAFE_OVERLAP
MODE: SAFE_OVERLAP_QA_EVIDENCE
NVDA_VERIFIED=NO

## Exact state basis

- Product under test: `full5/dev4-import-security-repair-20260822@6298899cb112336ef220caa8d0e52334ddc0c0ae`.
- Product PR #100 was not mutated.
- QA branch: `qa/dev4-postcommit-cleanup-evidence-20260822`.
- QA PR #127 remains DRAFT / EVIDENCE ONLY / DO NOT MERGE WHOLE BRANCH.
- New evidence commit: `1670bffa1202bdf49dd7e6479ade6542c94637da`.
- Hosted evidence run/job `32598483837 / 97093008824` checked exact QA head `1670bffa...`: diff hygiene PASS, compile PASS, focused result `4 failed, 1 passed`.
- Windows strict WIP=1 untouched. No Ctrl+A/Ctrl+C Product defect claim.

## PROVEN_PRODUCT_DEFECT 1 — cross-platform ChessBase privacy spans three serialized sinks

The previous adapter-only oracle was expanded without weakening it. On Ubuntu, the Windows-formatted private path `C:\Users\PrivateUser\Documents\Training Database.CBH` is still emitted with user/directory components because Product relies on host-native `Path.name` semantics.

Exact hosted failures now prove the same defect class in:
1. `ChessBaseSourceProbe.as_report_fields()`;
2. `ChessBaseIntegritySnapshot.as_report_fields()` / `SourceFileEvidence.as_report_fields()`;
3. `ChessBaseBundleManifest.as_dict()`.

This is one cross-platform sanitization defect with three affected serialized sinks. Fixing only `_report_name()` would leave integrity/manifest reporting false-green.

## PROVEN_PRODUCT_DEFECT 2 — no-clobber save can report failure after commit

The same exact run again reproduced the deterministic committed-but-reported-failed condition: `os.link(tmp, destination)` succeeds, destination contains the requested PGN, redundant temp unlink fails, and `save_pgn_atomic()` reports failure. Unsafe/ambiguous retry semantics remain proven.

The paired expected-hash CAS post-commit cleanup gate PASSED, so this remains localized to no-clobber post-link cleanup.

## Other classifications

- `QA_OR_ENVIRONMENT_ONLY`: prior local sandbox DNS failure; hosted Actions provide decisive evidence.
- `INCONCLUSIVE`: richer ChessBase provenance identifier semantics; never re-expose parent directories just to satisfy legacy tests.
- `QA_OR_ENVIRONMENT_ONLY / cross-lane`: DEV2 GameTree representation compatibility failures.
- `INCONCLUSIVE / outside ownership`: Stage1 native-menu/test-double failure.
- `HUMAN_ONLY`: exact fresh Windows/NVDA acceptance. `NVDA_VERIFIED=NO`.

## Next exact action

Remain SAFE OVERLAP until Product ownership is explicitly available. Then implement only two Product repairs: (A) one shared slash/backslash-neutral report-name sanitizer used consistently by adapter, integrity and manifest serialization, and (B) truthful committed-success semantics for no-clobber publication when redundant temp cleanup fails, with cleanup observability retained. Re-run newest strict evidence, all existing DEV4 focused gates, cross-lane PGN/ChessBase validation, full suites/diagnostic where applicable and exact-SHA CI. Do not enter overlapping ACSDB, DEV2 GameTree, DEV5 integration, Stage1 release or strict Windows ownership.
