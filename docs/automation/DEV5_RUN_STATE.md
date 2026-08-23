# DEV5_RUN_STATE

RUN_ID: 20260823-1347
STARTED_LOCAL: 2026-08-23 13:41 Europe/Uzhgorod
STATUS: COMPLETE
MODE: SAFE_OVERLAP_COORDINATION / STALE_PROMOTION_REVOKED / STAGE1_PRIVACY_REPAIR_GREEN_PENDING_INDEPENDENT_REVALIDATION
COORDINATOR_BRANCH: auto/dev5-coordinator-1348-20260823
SNAPSHOT_CUTOFF: 2026-08-23T13:47:22+03:00
SNAPSHOT_FILE: docs/automation/SNAPSHOT_20260823_1347.md

PRIOR_ACCEPTED_STAGE1_BASELINE_SHA: 0fa442330bc2bb03636ff9297512da4c29e38684
REVOKED_PREMATURE_PROMOTION_SHA: df52aeb3d99f4ae3d0089eab2882fe9b3c373dfd
CURRENT_STAGE1_REPAIR_CANDIDATE_SHA: 80720e8125c59a213f278668d599040f2768d553
PERSISTENT_FULL_PRODUCT_GREEN_SHA: dd9ebf9414103c805892856fe6a04706fa69039f
PR151_EXACT_CI_RUN: 32634572205
PR151_LINUX_JOB: 97182279775
PR151_WINDOWS_JOB: 97182279877
PR151_EXACT_CI_RESULT: SUCCESS
INDEPENDENT_EXACT_HEAD_REVALIDATION: PENDING
NVDA_VERIFIED: NO
FRESH_WINDOWS_CANDIDATE: NO
READY_FOR_RELEASE: NO

## Current ruling
Live GitHub superseded the prior 13:01 coordinator promotion. Independent QA PR #158 / `cf97ea4df62fee3330478c3fc40ee17bebdad4ec` / run-job `32632703773 / 97177751978` proved that `df52aeb3...` still leaked a private path embedded only inside arbitrary `OSError.strerror`. Therefore the prior promotion is revoked. No history is rewritten and no frozen ref is mutated.

DEV4 RUN_STATE `20260823-1300-stage1-oserror-strerror-privacy-proof` explicitly returned the minimal Stage1 repair to DEV5 ownership and required exact revalidation afterward. DEV5 repaired the existing PR #151 branch rather than opening a competing Product line.

Product repair commit `2fce7a799509f08f495f4289b49b03d620ba27cf` changes only `acs/import_registry.py::_batch_error_text`: user-facing batch filesystem errors no longer republish arbitrary `OSError.strerror`; they retain stable `Filesystem error` context, numeric errno when available, and report-safe `filename`/`filename2` observability. Strict `inspect()` behavior and internal exception/cause semantics remain intact.

Product regression commit `12b39b75173621e73eb9087586f0d6e35ed2004e` adds the path-bearing-strerror reproduction while preserving the existing requirement that a genuine OSError filename sidecar may expose only its safe basename.

Exact current PR #151 head is `80720e8125c59a213f278668d599040f2768d553`. `DEV5 Stage1 Path Privacy Repair CI` run `32634572205` is terminal SUCCESS:
- Linux `97182279775`: exact ancestry/diff hygiene PASS; compile PASS; Product privacy 10/10; unchanged current external privacy oracles 13/13 including PR #158; selected PGN privacy 2/2; drive-relative oracle PASS; unittest 663/663; pytest 741 + 758 subtests; SELFTEST + complete WebView2 diagnostic PASS.
- Windows Server 2025 `97182279877`: LF-exact checkout/ancestry/diff hygiene PASS; Product privacy 10/10; focused Stage1 release contracts 75/75; unittest 663/663; pytest 741 + 758 subtests; SELFTEST + complete WebView2 diagnostic PASS.

No skips, xfails, assertion weakening, GameTree/chess-state/UI/WebView/Teacher/Classroom/ACSDB or strict packaged UIA helper mutation was used.

`80720e8...` is therefore the current technically GREEN repaired Stage1 candidate, but it is NOT yet promoted as accepted Stage1 authority. The latest DEV4 ownership directive requires independent exact-head revalidation, and independent AUDIT_MASTER acceptance remains mandatory before a release-lineage promotion.

UIA classification remains C / INCONCLUSIVE at the QA synchronization-observability boundary: V2 proved the unique original Move Edit and native Backspace `e9 -> e`, then stopped before Ctrl+A on immediate SetValue readback. No Ctrl+A/C Product defect is proven.

NEXT_ACTION: independent DEV4/Audit must inspect exact `80720e8...`, PR #151 diff and run `32634572205`. If accepted, DEV5 may establish the new repaired Stage1 authority and start exactly one fresh Windows candidate chain locked to that exact Product. No candidate may be built from stale `df52aeb...` or old unpatched `0fa442...`.

READY_FOR_AUDITOR_READBACK=YES
READY_FOR_RELEASE=NO
NVDA_VERIFIED=NO
