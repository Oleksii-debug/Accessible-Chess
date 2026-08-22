# Accessible Chess autonomous next-wave directives

DIRECTIVE_VERSION: 0011
ISSUED_BY: DEV5 Coordinator/Integrator
EFFECTIVE_FROM_WAVE: 2026-08-22T10:00:00+03:00
SNAPSHOT_SEMANTICS: Workers already running before the effective wave must ignore this directive until their next invocation. Never abandon recoverable in-flight work because a newer directive appears.

## GLOBAL SNAPSHOT
Accepted Stage1 integration remains manual5/integration-20260821 @ 0fa442330bc2bb03636ff9297512da4c29e38684 with previously observed UI Semantic and Stage1 Saturation gates GREEN. No duplicate Stage1 intake or churn.

Full-product remains isolated and package-by-package. DEV1 is still canonically IN_PROGRESS, so SAFE OVERLAP remains mandatory for DEV5 until a later fresh cutoff proves touching lanes terminal. No wholesale PR #52/#65/#67/#68/#69/#72/#74 merge is authorized. Preserve one canonical chess/GameTree authority and all Windows/NVDA accessibility invariants.

## DEV1 — DIRECTIVE 0011
DEV1_RUN_STATE 20260822-0041 remains IN_PROGRESS on full5/dev1-accessible-shell-20260822. On next invocation, terminalize the branch at one exact Product SHA, update canonical RUN_STATE + 10_DEV1_HANDOFF_CURRENT, enumerate exact Product paths, and publish focused keyboard/focus/semantic evidence plus applicable observable CI. Do not duplicate GameTree/chess rules/backend ownership. FULL_PRODUCT_READY_FOR_INTEGRATION may become YES only after terminal completion at the same exact SHA.

## DEV2 — DIRECTIVE 0011
RUN_STATE 20260822-0838 is COMPLETE. Canonical Product head remains 63bae9c1f17032b2046b4137694dc99d195ed9ec. Validation-only PR #74 head 26abb02df7aae0dc4fc11615ca7494b628eed058 now has exact aggregate machine evidence: DEV2 Full Product Core CI run 32554979422 / job 96987608088 SUCCESS. Diff hygiene, compile, all focused GameTree gates, full unittest and full pytest succeeded; RUN_STATE records 707 PASS + 1 SKIP unittest and 787 passed + 1 skipped + 1294 subtests pytest. Prior rank/file ActionRegistry composition failure is closed using accepted Stage1 keybinding semantics in validation only. FULL_PRODUCT_DEV2_READY_FOR_INTEGRATION=YES. Do not merge PR #74 directly. Preserve canonical DEV2 Product and hand DEV5 exact composition provenance: canonical DEV2 head plus accepted UI/keybinding semantics only.

## DEV3 — DIRECTIVE 0011
Live GitHub technical truth pins latest verified executable Product head 86a2e6de3e1d89b939d31b6b5aa6de8100505c23 with exact DEV3 Full Product ACSDB CI run 32553387781 / job 96983670899 SUCCESS. Documentation-synchronized branch head is 6b31c601a4deb66a1cc9bbe3ed8dde0039a1eb4a and PR #65 marks READY_FOR_INTEGRATION=YES for the isolated ACSDB/Library/Search/recovery/query-plan + Training/Books persistence package. Canonical Drive 12_DEV3_HANDOFF_CURRENT is stale at 70321daf/32528057942. On next invocation, synchronize canonical Drive handoff to executable head 86a2e6de... and run 32553387781 before advancing the lane again. Do not ask DEV5 to intake a Drive-stale moving head.

## DEV4 — DIRECTIVE 0011
RUN_STATE 20260822-0802-full-product-qa is COMPLETE at QA head 38535dc85eed44496d2119e0e57cb9d45d08e327. Live PR #67 matches that head; exact commit-associated Actions remain absent, therefore QA stays INCONCLUSIVE. Six locked blockers govern PGN/external-format readiness: (1) symlink/reparse import indirection; (2) bounded untrusted PGN reads; (3) serialized local-path privacy; (4) expected_sha256 commit-boundary TOCTOU; (5) overwrite=False competing-creator lost update; (6) PGN export filesystem-indirection/symlink escape. Stockfish/UCI private-path redaction coverage is positive QA evidence, not a seventh defect. Continue strict deterministic regressions without weakening tests. Product fixes/equivalent reconciliations must preserve canonical DEV2/DEV3 publication semantics and avoid tools/qa/strict Windows workflow takeover.

## DEV5 — DIRECTIVE 0011
Take a fresh cutoff first. If any touching worker is IN_PROGRESS before cutoff, stay SAFE OVERLAP and do no competing Product push. Once DEV1 is terminal, the next safe assembly sequence is: canonical DEV2 Product 63bae9c1... + accepted DEV1 ActionRegistry/keybinding semantics proven by validation head 26abb02d...; exact GREEN DEV3 executable package 86a2e6de... after canonical handoff sync; DEV4 defect resolutions/equivalent reconciliations. Then create a validation-only PGN -> canonical GameTree -> ACSDB -> search/open composition and test malformed-input atomicity, bounded-resource behavior, no lost updates, path privacy/provenance, retry/recovery, keyboard/focus invariants and full repository regressions. Create/advance persistent full5 integration only after exact-SHA GREEN validation and auditable provenance.

PR #54/frozen refs remain protected. Rejected ZIPs are never reused. Fresh Windows candidate requires the complete machine release chain on the exact final audited Product SHA. NVDA_VERIFIED remains NO until the user personally verifies that exact candidate.
