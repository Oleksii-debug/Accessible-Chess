# DEV5_CURRENT_STATE

UPDATED_FROM_RUN: 20260823-2000
MODE: SAFE_OVERLAP / RELEASE_HOLD_D04_JSON_CANONICALITY / NO_PRODUCT_PUSH
SNAPSHOT_CUTOFF: 2026-08-23T16:59:32Z

Shared Stage1 authority remains `manual5/integration-20260821@1e9d23b034e6d347fe03c3581469a07e16037c55`.

D05 promotion surface PR #222 remains open/draft at exact `release/d05-stage1-authority-promotion-bridge-20260823@88578e05eb0ea51795570f92f76428b9e029c11d`. Its dual-OS combined run `32641454103` remains GREEN for the tree it contains, but that SHA is superseded and must not be promoted.

D04 PR #239 exact `53791a44176627b012f72c3ac5b7720214194975` remains terminal GREEN for Stockfish source-ZIP resource bounds, and QA-only PR #241 previously proved that #239 composes with the current D05 tree. However #239 itself is now proven release-defective by newer admissible terminal evidence.

D04 QA-only PR #249 exact QA head `811ba1c8bb15aeb1241087822f45136e6ee537e8` tested exact #239 Product parent. Workflow run `32647323503` is terminal RED in the proving sense: Ubuntu `97213449826` and Windows `97213449888` both pass exact ancestry/scope, compile, and existing D04/release-preflight regressions, then fail exactly 2/2 new duplicate-key assertions because `ReleasePreflightError` is not raised. The accepted ambiguous release bytes use duplicate `nvda_verified` and duplicate `nvda_menu_usability` keys. Root cause is `_read_json_object()` using ordinary `json.loads()` last-key-wins behavior.

Classification is `PROVEN_PRODUCT_DEFECT / P1 / RELEASE_EVIDENCE_JSON_CANONICALITY`. Required owner contract is D04: reject duplicate JSON object keys at every nesting level before semantic validation while preserving malformed/unreadable JSON containment and all valid release-evidence semantics. The PR #249 oracle must remain unchanged.

No terminal D04 owner repair for this exact defect was found before this cutoff. Therefore D05 must NOT selectively intake #239 as the final cumulative release-preflight source yet, must NOT move shared authority, and must NOT start a Windows candidate. The next release-source composition must include terminal owner repair of #249 in addition to cumulative #218/#228/#239 behavior.

This DEV5 wave remains SAFE OVERLAP because D04 owns the release-preflight Product defect and D05 PR #222 owns touching Stage1 composition. No competing Product push was made.

Old V5 and all old/rejected ZIPs remain forbidden for release use.

AUTHORITY_PROMOTED=NO
FRESH_WINDOWS_CANDIDATE=NO
READY_FOR_RELEASE=NO
NVDA_VERIFIED=NO
