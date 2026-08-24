# Accessible Chess — Final Work Master current state

Updated UTC: 2026-08-24T08:36:07Z

## Authorities

- `CURRENT_STAGE1_AUTHORITY`: `manual5/integration-20260821@1e9d23b034e6d347fe03c3581469a07e16037c55`
- `CURRENT_STAGE1_PROMOTION_SOURCE`: none yet. D04 repair PR #260 is at `work/final-master-stage1-20260824@41490f247cfd1146cd5331d9c109a78babe4fd9f`, based on exact terminal Product parent `53791a44176627b012f72c3ac5b7720214194975`; former D05 bridge `88578e05eb0ea51795570f92f76428b9e029c11d` remains stale and must not be promoted.
- `CURRENT_FULL_PRODUCT_AUTHORITY`: `full5/dev5-compose-1700-20260822@dd9ebf9414103c805892856fe6a04706fa69039f`
- `CURRENT_OWNER`: Final Work Master owns the unclaimed D04 release-JSON repair and subsequent selective Stage1 convergence. D05 remains the historical integration contract owner; independent Audit must accept the exact recomposed SHA before promotion.
- `WORK_BRANCH`: `work/final-master-stage1-20260824`, created from exact D04 Product parent `53791a44176627b012f72c3ac5b7720214194975`.

## Release state

- `CURRENT_RELEASE_BLOCKER`: D04 Product repair PR #260 exists at exact head `41490f247cfd1146cd5331d9c109a78babe4fd9f`. Product-only commit `5ad2bd1a7a88fd05e5539c2fd64e1efa454b338a` rejects duplicate object keys centrally; owner regression commit `ff6affec0b59a1e53a648ad39f2302f8807b91a7` covers all release documents, nested duplicates and error privacy. Exact dual-OS run `32706472382` is `QUEUED` (Ubuntu job `97368540796`; Windows job `97368540543`), so audit and D05 intake remain blocked.
- `CURRENT_FULL_PRODUCT_BLOCKERS`: PR #257 at `2833af8484761d60cd949e181644c258b7bb5052`, run `32659863111`, proves that PR #235 engine composition loses the accepted #225 hard-shutdown kill/reap contract. Full Product intake remains inactive until the Stage1 human gate closes.
- `OPEN_ACTIVE_OVERLAPS`: PR #249 is QA-only and immutable; its oracle blob `457d8e50d8a30adc9bd5de592f3eff6eedc862c8` was replayed unchanged. PR #260 is the sole active D04 Product repair. PRs #241/#257/#238 remain QA or validation overlays and are not Product intake candidates.
- `FRESH_WINDOWS_CANDIDATE`: `NO`
- `ROBOT_TEST_READY`: `NO` for a new exact promoted source
- `NVDA_VERIFIED`: `NO`
- `STAGE2`: `BLOCKED`

## Next exact action

Wait for both jobs of exact run `32706472382`. On dual-OS green, post an exact-SHA audit handoff for PR #260. Only after independent acceptance, build a selective D05 successor as a normal descendant of `1e9d23b034e6d347fe03c3581469a07e16037c55`, preserving accepted D01/D02/D03 blobs and taking only the current D04 Product/tests. Do not create a Windows candidate before that audit.

## Live selective-intake matrix

`main@a70725e72c7287e0f2b76ff8740d5b71ac5108f7` is the repository default branch but currently contains unrelated WordDeck work and is not an Accessible Chess release authority.

| Plane | Package | Exact head | Classification | Selective treatment |
|---|---|---|---|---|
| Stage1 | D01 PR #197 | `cf28971d5bf3c33c3409e069a817fc884f8244fe` | `ACCEPTED_SELECTIVE` | Preserve the Move Submit routing Product blob and owner regression; exclude its workflow/validation history. |
| Stage1 | D05 PR #195 | `74f39ed61c46ec2f5dc989275f1a095bd12d7f30` | `SUPERSEDED` | Historical combined Product source only; later D04/D03 fixes make it insufficient. |
| Stage1 | D04 PR #218 | `579938cf422445b5c46a08c00cae284e3ae08b9b` | `SUPERSEDED` | Product/test contract is cumulative in #228/#239; do not intake the old workflow. |
| Stage1 | D03 PR #225 | `d3f3e8e49fa9e9932e9c66d7c85f67cbfc7e7347` | `ACCEPTED_SELECTIVE` | Preserve `acs/engine.py` hard-shutdown Product semantics and unchanged lifecycle regression. |
| Stage1 | D04 PR #228 | `0dae9b62fd4f152a5f362674e11039ad34b481c3` | `SUPERSEDED` | Product/test contract is cumulative in #239; exclude validation workflow history. |
| Stage1 | D04 PR #239 | `53791a44176627b012f72c3ac5b7720214194975` | `ACCEPTED_SELECTIVE` | Current D04 Product parent, including source-ZIP resource bounds and owner tests. |
| Stage1 | D04 PR #241 | `c40dde4c6bc20b63b82e259fcd1ed003c403ac18` | `QA_ONLY` | One validation workflow only; never intake as Product. |
| Stage1 | D04 PR #249 | `811ba1c8bb15aeb1241087822f45136e6ee537e8` | `QA_ONLY` + `PROVEN_DEFECT` | Oracle kept unchanged and replayed by #260; never intake as Product. |
| Stage1 | D04 PR #260 | `41490f247cfd1146cd5331d9c109a78babe4fd9f` | `PRODUCT_REPAIR` + `CI_QUEUED` | Central duplicate-key rejection plus owner tests; local full gate is green, dual-OS run `32706472382` must finish green before independent audit. |
| Stage1 | D05 PR #222 | `88578e05eb0ea51795570f92f76428b9e029c11d` | `STALE` | Do not promote; it predates #239 and the duplicate-key repair. |
| Stage1 | D03 PR #258 | `74f39ed61c46ec2f5dc989275f1a095bd12d7f30` | `VALIDATION_ONLY` + `STALE` | Supporting real-engine evidence only; not a Product source or current promotion candidate. |
| Full Product | D02 PR #233 | `7e2d0217caa141bcbd779601cbf6aa6dcd3ba6c4` | `NEEDS_AUDIT` | Select Product/tests only after empty-square attackers/defenders contract is reconciled; do not import conflicting semantics. |
| Full Product | D03 PR #235 | `61e381b2aa8755590082a6e15a61edc5a6774879` | `BLOCKED_PRODUCT_DEFECT` | Output-bound Product/tests are valuable, but `acs/engine.py` cannot be taken wholesale until #225 lifecycle is composed. |
| Full Product | D03 PR #257 | `2833af8484761d60cd949e181644c258b7bb5052` | `QA_ONLY` | Immutable composition oracle; never Product intake. |
| Full Product | D06 PR #215 | `3b98248107aa67929c9d608995d7da99969ac83a` | `READY_FOR_SELECTIVE_INTAKE` | Product codec/GameTree delta plus owner tests after Stage1 human gate; exclude workflow/CI-base overlays. |
| Full Product | D07 PRs #219/#231/#237/#240/#242 | terminal `bb41744fc05ecad19620bfbb6f17d1edd4ca0222` | `READY_FOR_SELECTIVE_INTAKE` | Treat as one dependency-ordered migration/import/search Product chain with owner tests. |
| Full Product | D07 PRs #224/#227 | `7bc1bb4…` / `9503f98…` | `SUPERSEDED` | Contracts are carried by later cumulative D07 descendants; do not separately merge old workflow history. |
| Full Product | D08 PRs #223/#232 | terminal `67618387e8bb8055037cf17aca3923d484368cb0` | `READY_FOR_SELECTIVE_INTAKE` | Product training/provenance adapters and owner tests after their dependencies. |
| Full Product | D08 PR #238 | `02b0630abd72b3bf6d157e3f6614f3c4822cc6b4` | `QA_ONLY` | Ownership-correct fixture composition evidence only. |
| Full Product | DEV1 PRs #115/#122 | terminal source `edc979e783942403049997874eb966592d3a67d8` | `NEEDS_AUDIT` | Select current Library/Books WebView Product blobs and owner tests; exclude validation PR #126/workflows. |
| Full Product | DEV4 PR #100 | `3e15dc2e844cb825e482317fd024795130147011` | `NEEDS_AUDIT` | Large ChessBase/import/security ancestry: intake exact current Product blobs only after capability/provenance review; validation overlays are not Product. |
| Full Product | DEV-A PR #170 | `b66ffccf963fb8b44e4084158cb7b9bdcfb9fe97` | `NEEDS_AUDIT` | Role-safe TeachingSession bridge; late dependency-ordered intake only. |
| Full Product | D09 PR #214 | `59fedaa139a26f848f60af345ac429163ea344b7` | `NEEDS_AUDIT` | Teacher/Classroom Product/tests are retained for late intake; never mix into Stage1. |
| Full Product | D10 PR #213 | `80ba9be3f4698b3810e3d6cb2e8b264143f4554f` | `SUPERSEDED` | Parent of cumulative #234. |
| Full Product | D10 PR #234 | `6ab731b2cd7a4295395c2ab1fafe7523b369465f` | `NEEDS_AUDIT` | Compound workspace Product/tests only; replace inherited stale D01 test overlay during later composition, not D10 Product behavior. |

No Full Product package in this matrix is authorized for activation while Issue #22 human Stage1 acceptance remains open.

## Latest local exact-head evidence

- `python -m unittest discover -s tests`: `813 tests PASS`.
- `python -m pytest -q tests`: `891 passed, 830 subtests passed`.
- `python -m acs.selftest`: `PASS`.
- `python run_accessible_chess.py --diagnostic`: `ACCESSIBLE CHESS 0.4 WEBVIEW2 COMPLETE USER FLOW DIAGNOSTIC PASS`.
- `git diff --check`: `PASS`.
