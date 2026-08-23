# DEV4 RUN STATE

RUN_ID: 20260823-0800-import-registry-privacy-proof
STATUS: COMPLETE / SAFE_OVERLAP / PRODUCT_HOLD / QA_ONLY
MODE: DEV4_INDEPENDENT_QA_EVIDENCE
ROLE: DEV4 independent QA/evidence/security
NVDA_VERIFIED=NO
READY_FOR_RELEASE=NO
READY_FOR_DEV5_INTAKE=NO

## Canonical Product

- `full5/dev4-import-security-repair-20260822 @ 3e15dc2e844cb825e482317fd024795130147011` remains live-identical.
- No Product code was modified in this run.
- Existing QA PR #146 remains RED for five PGN save/concurrency diagnostic path leaks.

## New exact QA evidence

- QA branch: `qa/dev4-import-registry-path-privacy-20260823`.
- QA PR #147: OPEN / DRAFT / VALIDATION ONLY / DO NOT MERGE.
- Exact QA head: `0d21050bcf67fa9108de52646780ce6d29c1bd86`.
- Hosted workflow: `DEV4 Import Registry Path Privacy Evidence`.
- Run/job: `32619282734 / 97144841859` — FAILURE.
- Exact checkout PASS; `git diff --check` PASS; compile PASS; focused privacy oracle `3 failed in 0.07s`.

## PROVEN_PRODUCT_DEFECT — ImportRegistry diagnostic/report path privacy

Exact hosted failures prove absolute private workstation paths cross the application-facing import preflight boundary:

1. `SourceProvenanceError` exposes `/tmp/.../Users/PrivateUser/Documents/analysis.pgn`.
2. `SourceMutationError` exposes `/tmp/.../Users/PrivateUser/Documents/analysis.pgn`.
3. `inspect_batch()` republishes the provenance exception text through `BatchInspectionItem.error`, retaining the same private parent directories.

The established shared contract in `acs/report_paths.py::report_safe_name()` requires absolute POSIX/Windows/UNC workstation paths to reduce to safe basename/provenance. `analysis.pgn` may remain; private parents must not.

This is independent of PR #146's five PGN save/concurrency diagnostic leaks. Current Product HOLD therefore contains two separate privacy defect classes.

## Classification

- `PROVEN_PRODUCT_DEFECT`: ImportRegistry mutation/provenance diagnostics and batch error payload leak absolute private paths.
- `PROVEN_PRODUCT_DEFECT`: five PGN save/concurrency path-bearing diagnostics remain RED in PR #146.
- `QA_OR_ENVIRONMENT_ONLY`: none newly observed in this run.
- `INCONCLUSIVE`: Windows-specific filesystem semantics not exercised here.
- `HUMAN_ONLY`: exact fresh Windows/NVDA usability.

## Boundaries

No Product mutation. No ACSDB schema mutation. No GameTree mutation. No Stage1/frozen-ref mutation. No DEV5 integration mutation. Windows strict WIP=1 untouched. No Ctrl+A/Ctrl+C Product claim. No test weakening or force-push.

## Next action

After authorized Product repair, rerun unchanged PR #147 three-case oracle and PR #146 five-case oracle plus import-registry/import-contract/ChessBase/PGN path/resource/concurrency/recovery/post-commit regressions and exact-head full relevant CI. Minimal repair should sanitize only user-facing diagnostic/report rendering while preserving internal verification paths, exception classes, source mutation/provenance detection, batch continuation, and publication semantics.
