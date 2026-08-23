# DEV5_SESSION_HANDOFF

RUN: 20260823-2000
COORDINATOR_BRANCH: `auto/dev5-coordinator-2000-20260823`
MODE: SAFE_OVERLAP / RELEASE_HOLD_D04_JSON_CANONICALITY / NO_PRODUCT_PUSH
SNAPSHOT: `docs/automation/SNAPSHOT_20260823_2000.md`
CUTOFF: `2026-08-23T16:59:32Z / 19:59 Europe/Kyiv`

Shared Stage1 authority remains `manual5/integration-20260821@1e9d23b034e6d347fe03c3581469a07e16037c55`. D05 PR #222 remains the touching promotion surface at exact `88578e05eb0ea51795570f92f76428b9e029c11d`; that SHA remains superseded and is not a release target.

D04 #239 exact `53791a44176627b012f72c3ac5b7720214194975` remains terminal GREEN for source-ZIP resource limits and compatible with the current D05 tree by QA-only #241. But D04 QA-only #249 has now become admissible terminal evidence and proves an additional P1 directly on exact #239.

PR #249 exact QA head `811ba1c8bb15aeb1241087822f45136e6ee537e8`, run `32647323503`: Ubuntu `97213449826` and Windows `97213449888` both pass exact ancestry/scope, compile and the old D04/preflight regression block, then fail exactly 2/2 new assertions because duplicate JSON object keys are accepted. The proven conflicting release-manifest keys are `nvda_verified` and `nvda_menu_usability`. Root cause is `_read_json_object()` using ordinary `json.loads()` with last-key-wins behavior.

Classification: `PROVEN_PRODUCT_DEFECT / P1 / RELEASE_EVIDENCE_JSON_CANONICALITY`. D04 owns repair. Required owner semantics: reject duplicate keys at every object nesting level before semantic validation; preserve malformed/unreadable JSON error containment and current valid release semantics; replay #249 unchanged. No terminal owner repair for this exact defect was found before this cutoff.

Consequently the previous route `#239 intake -> D05 combined gate` is paused. Correct route is: terminal D04 owner repair of #249 -> unchanged #249 + cumulative #218/#228/#239 dual-OS/full-suite proof -> independent acceptance of that cumulative D04 head -> D05 selective intake into PR #222 -> new exact combined dual-OS gate with all immutable Stage1 oracles -> fresh Audit-A/B -> force=false authority fast-forward -> exactly one fresh Windows strict chain.

This wave stayed in SAFE OVERLAP and made no Product push, authority movement, candidate build, force-push, frozen-ref movement, PR54 merge, or test weakening. Old V5 and every old/rejected ZIP remain forbidden.

Next DEV5 invocation must establish a fresh cutoff. Evidence or repairs published after this cutoff may be observed but must not be used to coordinate DEV1-DEV4 until the next cutoff.

AUTHORITY_PROMOTED=NO
FRESH_WINDOWS_CANDIDATE=NO
READY_FOR_RELEASE=NO
NVDA_VERIFIED=NO
READY_FOR_AUDITOR_READBACK=YES
