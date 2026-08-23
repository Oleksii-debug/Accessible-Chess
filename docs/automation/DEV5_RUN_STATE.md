# DEV5_RUN_STATE

RUN_ID: 20260823-1701
STARTED_LOCAL: 2026-08-23 17:01 Europe/Kyiv
STATUS: COMPLETE
MODE: SAFE_OVERLAP / RELEASE_HOLD_D04_239 / NO_PRODUCT_PUSH
COORDINATOR_BRANCH: auto/dev5-coordinator-1701-20260823
SNAPSHOT_CUTOFF: 2026-08-23T14:01:47Z
SNAPSHOT_FILE: docs/automation/SNAPSHOT_20260823_1701.md

SHARED_STAGE1_AUTHORITY: 1e9d23b034e6d347fe03c3581469a07e16037c55
D05_PROMOTION_PR: 222
SUPERSEDED_COMBINED_HEAD: 88578e05eb0ea51795570f92f76428b9e029c11d
SUPERSEDED_COMBINED_RUN: 32641454103
SUPERSEDED_WINDOWS_JOB: 97199059495
SUPERSEDED_UBUNTU_JOB: 97199059664
NEW_REQUIRED_D04_PR: 239
NEW_REQUIRED_D04_HEAD: 53791a44176627b012f72c3ac5b7720214194975
NEW_REQUIRED_PREFLIGHT_BLOB: 9213efc03e78756ec7d45f5983c91414b614b06f
NEW_REQUIRED_D04_RUN: 32641696408
NEW_REQUIRED_D04_WINDOWS_JOB: 97199654106
NEW_REQUIRED_D04_UBUNTU_JOB: 97199654044
D04_239_AUDIT_SELECTIVE_INTAKE: ACCEPTED
FRESH_WINDOWS_CANDIDATE: NO
READY_FOR_RELEASE: NO
NVDA_VERIFIED: NO

## Current ruling
Exact D05 PR #222 head `88578e05...` remains dual-OS machine GREEN for the scope it contains, but it is superseded as final source-promotion target because D04 PR #239 became terminal before this cutoff and proves a newer Stage1 P1 release-resource defect.

D04 #239 proves the old cumulative preflight could enter `ZipFile.testzip()` without fail-closed bounds on bundled Stockfish source ZIP compressed bytes, entry count, one uncompressed member, or total uncompressed payload. Red-first run `32641610135` failed unchanged proving cases on both OS after ancestry/scope/compile PASS. Minimal repair head `53791a44...` sets pre-testzip bounds: 8 MiB archive, 4096 entries, 16 MiB/member, 64 MiB total uncompressed. Final run `32641696408` is terminal SUCCESS: Ubuntu `97199654044`, Windows `97199654106`, focused 22/22, prior D04/preflight/privacy GREEN, full unittest/pytest, SELFTEST and diagnostic GREEN.

AUDIT-A independently accepted D04 #239 for selective Stage1 intake and explicitly ruled `88578e05...` non-final. Required next release-source action belongs to existing D05 PR #222: selectively replace cumulative `acs/release_preflight.py` with blob `9213efc...`, add `tests/test_d04_stockfish_source_zip_bounds.py`, preserve all accepted Stage1 blobs and D03 hard-shutdown, refresh exact provenance locks, and rerun one combined dual-OS gate including #218/#228/#239 plus PR159/193/196 and lifecycle/full-suite evidence.

Because PR #222 is already the active promotion surface and this exact intake was routed to D05, this DEV5 wave is SAFE OVERLAP. No competing Product commit, promotion, candidate chain, force-push, frozen-ref move, PR54 merge, or test weakening was performed.

Old V5 remains forensic only and every old/rejected ZIP remains forbidden. No fresh Windows candidate may start until the newest recomposed exact SHA receives fresh exact-SHA Audit acceptance and shared authority is fast-forwarded without force.

READY_FOR_AUDITOR_READBACK=YES
READY_FOR_RELEASE=NO
NVDA_VERIFIED=NO
