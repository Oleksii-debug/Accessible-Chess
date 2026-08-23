# DEV5_RUN_STATE

RUN_ID: 20260823-2000
STARTED_LOCAL: 2026-08-23 20:00 Europe/Kyiv
STATUS: COMPLETE
MODE: SAFE_OVERLAP / RELEASE_HOLD_D04_JSON_CANONICALITY / NO_PRODUCT_PUSH
COORDINATOR_BRANCH: auto/dev5-coordinator-2000-20260823
SNAPSHOT_CUTOFF: 2026-08-23T16:59:32Z
SNAPSHOT_FILE: docs/automation/SNAPSHOT_20260823_2000.md

SHARED_STAGE1_AUTHORITY: 1e9d23b034e6d347fe03c3581469a07e16037c55
D05_PROMOTION_PR: 222
SUPERSEDED_COMBINED_HEAD: 88578e05eb0ea51795570f92f76428b9e029c11d
D04_RESOURCE_BOUNDS_PR: 239
D04_RESOURCE_BOUNDS_HEAD: 53791a44176627b012f72c3ac5b7720214194975
D04_DUPLICATE_JSON_QA_PR: 249
D04_DUPLICATE_JSON_QA_HEAD: 811ba1c8bb15aeb1241087822f45136e6ee537e8
D04_DUPLICATE_JSON_PROVING_RUN: 32647323503
D04_DUPLICATE_JSON_UBUNTU_JOB: 97213449826
D04_DUPLICATE_JSON_WINDOWS_JOB: 97213449888
D04_DUPLICATE_JSON_CLASSIFICATION: PROVEN_PRODUCT_DEFECT_P1_RELEASE_EVIDENCE_JSON_CANONICALITY
D04_DUPLICATE_JSON_OWNER_REPAIR_AT_CUTOFF: NOT_FOUND_TERMINAL
AUTHORITY_PROMOTED: NO
FRESH_WINDOWS_CANDIDATE: NO
READY_FOR_RELEASE: NO
NVDA_VERIFIED: NO

## Current ruling
The previous coordinator wave quarantined PR #249 because its terminal readback appeared after that wave's cutoff. At this run's new cutoff the evidence is admissible and changes release ordering.

PR #249 is QA-only and tests exact D04 #239 Product parent. Run `32647323503` is a valid RED-first Product proof: both OS pass exact ancestry/scope, compile, and the existing D04/release-preflight suites before failing exactly the two new duplicate-key cases because ordinary `_read_json_object()` / `json.loads()` accepts conflicting duplicate object keys with last-key-wins semantics. Ubuntu existing suite is 84/84 GREEN; Windows is 84 OK with 2 platform-appropriate skips. The two targeted failures cover duplicate `nvda_verified` and duplicate `nvda_menu_usability` release truth.

This is a release evidence false-green boundary and is classified `PROVEN_PRODUCT_DEFECT / P1 / RELEASE_EVIDENCE_JSON_CANONICALITY`. D04 owns the Product repair. Required behavior is duplicate-key rejection at every JSON object nesting level before semantic validation, with existing malformed/unreadable containment and valid release semantics preserved. The #249 oracle is immutable for repair proof.

No separate terminal D04 owner repair for this exact defect was found before the cutoff. Therefore #239 cannot yet be the final cumulative D04 intake into D05 PR #222. D05 release promotion remains on hold; shared authority does not move; no Windows candidate chain starts.

Because D04 owns the active release-preflight repair and D05 PR #222 owns touching Stage1 composition, DEV5 remains SAFE OVERLAP and makes no competing Product commit. Coordinator work is limited to evidence classification, conflict/order control, and durable directives.

READY_FOR_AUDITOR_READBACK=YES
READY_FOR_RELEASE=NO
NVDA_VERIFIED=NO
