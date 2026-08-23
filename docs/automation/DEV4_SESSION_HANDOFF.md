# DEV4 SESSION HANDOFF

SESSION: 20260823-0800 ImportRegistry diagnostic privacy proof
STATUS: COMPLETE / SAFE_OVERLAP / PRODUCT_HOLD / QA_ONLY
ROLE: DEV4 independent QA/evidence/security
NVDA_VERIFIED=NO
READY_FOR_RELEASE=NO
READY_FOR_DEV5_INTAKE=NO

## Exact state basis

- Canonical Product: `full5/dev4-import-security-repair-20260822 @ 3e15dc2e844cb825e482317fd024795130147011`, live-identical and not mutated.
- Existing QA-only PR #146 remains authoritative RED evidence for five PGN save/concurrency diagnostic path leaks.
- New QA-only PR #147 proves a separate ImportRegistry diagnostic/report path leak.
- PR #147 exact evidence head: `0d21050bcf67fa9108de52646780ce6d29c1bd86`.
- Hosted run/job: `32619282734 / 97144841859` — FAILURE.
- Exact checkout PASS; diff hygiene PASS; compile PASS; focused privacy gate `3 failed in 0.07s`.

## New PROVEN_PRODUCT_DEFECT

`ImportRegistry.inspect()` renders the submitted source path directly into `SourceMutationError` and `SourceProvenanceError`. Exact hosted evidence with a source under `Users/PrivateUser/Documents/analysis.pgn` shows those private parent directories in both exception strings. `inspect_batch()` then republishes the provenance error through `BatchInspectionItem.error`, carrying the same leak into batch preflight/report output.

The existing report-only sanitizer contract already exists in `acs/report_paths.py::report_safe_name()`. Correct repair is path rendering only: keep safe filename/provenance visible while absolute workstation parent directories are redacted. Internal source paths must remain usable for fingerprinting and re-verification.

## Current Product HOLD

Two independent privacy defect classes are now proven on `3e15dc2e...`:
1. PR #146 — five PGN save/concurrency path-bearing diagnostics leak private parent directories.
2. PR #147 — ImportRegistry mutation/provenance diagnostics and batch error payload leak private parent directories.

Do not lift HOLD from old GREEN evidence that predated these strict oracles.

## Boundaries / classification

- `PROVEN_PRODUCT_DEFECT`: both privacy classes above.
- `QA_OR_ENVIRONMENT_ONLY`: none new.
- `INCONCLUSIVE`: Windows-specific filesystem behavior outside this Linux privacy proof.
- `HUMAN_ONLY`: exact fresh Windows/NVDA usability.
- No Product mutation, ACSDB schema mutation, GameTree mutation, Stage1/frozen-ref mutation, DEV5 integration mutation or Windows strict duplication.
- No Ctrl+A/Ctrl+C Product defect claim. No test weakening. No force-push.

## Next action

After authorized Product repair, rerun unchanged PR #147 3-case oracle and PR #146 5-case oracle, then full relevant import-registry/import-contract/ChessBase/PGN path/resource/concurrency/recovery/post-commit regression surfaces and exact-head CI. `NVDA_VERIFIED=NO`.
