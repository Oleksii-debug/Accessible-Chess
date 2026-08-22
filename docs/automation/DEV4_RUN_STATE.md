# DEV4 RUN STATE

RUN_ID: 20260823-0002-full-product-qa
STATUS: COMPLETE_WITH_TWO_PROVEN_PRODUCT_DEFECTS_IN_SAFE_OVERLAP
MODE: SAFE_OVERLAP_QA_EVIDENCE
ROLE: DEV4 independent QA/evidence/security
DIRECTIVE: AUDIT-20260822-1900-01 + DEV5-0028 coordination context
NVDA_VERIFIED=NO

## Exact live state

- Product under test remains `full5/dev4-import-security-repair-20260822@6298899cb112336ef220caa8d0e52334ddc0c0ae`.
- Product PR #100 was not mutated.
- QA branch: `qa/dev4-postcommit-cleanup-evidence-20260822`.
- QA PR #127 remains DRAFT / EVIDENCE ONLY / DO NOT MERGE WHOLE BRANCH.
- New evidence commit: `1670bffa1202bdf49dd7e6479ade6542c94637da` — expands the cross-platform ChessBase privacy oracle across adapter, integrity snapshot and manifest serialized sinks.
- Exact hosted run/job: `32598483837 / 97093008824` on exact QA head `1670bffa1202bdf49dd7e6479ade6542c94637da`.
- Diff hygiene PASS; compile PASS; focused QA result `4 failed, 1 passed`.
- Windows strict WIP=1 untouched. No Ctrl+A/Ctrl+C Product claim.

## PROVEN_PRODUCT_DEFECT 1 — cross-platform ChessBase report privacy is broader than adapter-only

The established report/privacy contract forbids workstation directory leakage. Product currently uses host-native `Path.name` in three serialized surfaces. On Ubuntu, Windows-formatted backslashes are ordinary filename characters, so `C:\Users\PrivateUser\Documents\Training Database.CBH` is emitted unchanged.

Exact hosted QA independently failed all three privacy gates:
1. `ChessBaseSourceProbe.as_report_fields()` / adapter source_path;
2. `ChessBaseIntegritySnapshot.as_report_fields()` including primary_path/file path;
3. `ChessBaseBundleManifest.as_dict()` including primary_path/component path.

This remains one defect class with three affected sinks, not three independent defect classes. Any Product repair that fixes only `_report_name()` is incomplete/false-green.

## PROVEN_PRODUCT_DEFECT 2 — PGN no-clobber committed-but-reported-failed

Exact hosted QA again reproduced the existing finding: after successful `os.link(tmp, destination)`, a failure removing the redundant temp pathname propagates as save failure although the requested destination is already committed. This creates ambiguous unsafe retry semantics.

The expected-hash CAS cleanup companion test remains PASS, so do not generalize this defect to expected-hash publication.

## Classification

- `PROVEN_PRODUCT_DEFECT`: path-syntax-neutral ChessBase report sanitization missing across adapter/integrity/manifest serialized sinks.
- `PROVEN_PRODUCT_DEFECT`: no-clobber post-link cleanup can report failure after commit.
- `QA_OR_ENVIRONMENT_ONLY`: prior local sandbox DNS failure; hosted Actions supplied decisive evidence.
- `INCONCLUSIVE`: richer provenance naming contract; do not restore parent directories without a separate privacy-safe identifier design.
- `INCONCLUSIVE / outside ownership`: Stage1 native-menu/test-double failure.
- `QA_OR_ENVIRONMENT_ONLY / cross-lane`: DEV2 GameTree representation compatibility failures.
- `HUMAN_ONLY`: fresh Windows/NVDA usability; `NVDA_VERIFIED=NO`.

## Next action

Remain SAFE OVERLAP until Product ownership is explicitly available. Authorized Product repair must (A) use one shared path-syntax-neutral report-name sanitizer across adapter, integrity and manifest DTO serialization, and (B) preserve truthful committed-success semantics after successful no-clobber publication even if redundant temp cleanup fails, while keeping cleanup observability. Then run this focused evidence, all existing DEV4 gates, cross-lane PGN/ChessBase validation and exact-SHA CI. Avoid `acs/acsdb.py` while DEV3/DEV5 semantic overlap remains active.
