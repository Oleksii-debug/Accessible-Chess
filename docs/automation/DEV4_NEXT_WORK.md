# DEV4 NEXT WORK

NEXT_ACTION_ORDER:

1. Re-read live Product PR #100, QA PR #127 exact head/Actions, DEV5/integration state, canonical Drive handoff and RUN_STATE before any mutation.
2. Preserve SAFE OVERLAP while Product/integration owners are active. QA branch remains evidence-only unless a later directive explicitly transfers Product ownership.
3. Two Product defect classes remain proven; exact newest evidence run/job is `32598483837 / 97093008824` on QA head `1670bffa1202bdf49dd7e6479ade6542c94637da`, with diff/compile PASS and focused `4 failed, 1 passed`.
4. Product repair priority A — ChessBase cross-platform report privacy must cover ALL serialized sinks, not only `chessbase_adapter._report_name()`: adapter report fields, `ChessBaseIntegritySnapshot.as_report_fields()`/`SourceFileEvidence.as_report_fields()`, and `ChessBaseBundleManifest.as_dict()` must all use one path-syntax-neutral sanitizer that strips both `/` and `\\` parents.
5. Do not restore raw parent directories merely to satisfy legacy provenance expectations. If richer provenance is required, define a separate opaque/report-safe identifier contract.
6. Product repair priority B — after successful no-clobber `os.link`, failure to unlink the redundant temp pathname must not make the save API report publication failure. Preserve cleanup observability without lying about commit state or creating unsafe retry behavior.
7. The paired expected-hash CAS cleanup gate PASSED again; do not generalize the no-clobber defect to expected-hash publication.
8. Preserve all earlier DEV4 security repairs and strict gates: symlink/reparse/special-file rejection, bounded PGN reads, stable fingerprints, ChessBase I/O observability, ACSDB error redaction, lossy-encoding quality downgrade, batch continuation, PGN path-indirection rejection, no-clobber publication, expected-hash recovery, recovery-snapshot preservation.
9. Keep `acs/acsdb.py` Product mutation out of this lane while DEV3 schema/search work remains semantically overlapping under DEV5 coordination; continue read-only sink/error/privacy evidence only.
10. Keep GameTree comment/missing-termination semantics in DEV2 ownership. Keep Stage1 native-menu/test-double failures outside DEV4 absent a concrete security/package boundary.
11. After authorized Product repair, run the two QA files first, then all existing DEV4-focused gates, cross-lane PGN/ChessBase checks, full unittest/pytest/diagnostic where applicable, and exact-SHA CI.
12. Windows strict WIP=1. No Ctrl+A/Ctrl+C Product claim without exact proof. `NVDA_VERIFIED=NO`.

CURRENT QA BRANCH: `qa/dev4-postcommit-cleanup-evidence-20260822`
CURRENT QA PR: #127
LATEST EVIDENCE COMMIT: `1670bffa1202bdf49dd7e6479ade6542c94637da`
LATEST HOSTED EVIDENCE: run/job `32598483837 / 97093008824` -> FAILURE, `4 failed, 1 passed`.

FAILED privacy surfaces:
- adapter source report;
- integrity snapshot/source evidence report;
- manifest primary/component report.

FAILED PGN surface:
- no-clobber committed-but-reported-failed cleanup condition.

PASS:
- expected-hash CAS post-commit cleanup companion gate.
