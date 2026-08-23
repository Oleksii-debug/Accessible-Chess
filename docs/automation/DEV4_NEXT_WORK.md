# DEV4 NEXT WORK

NEXT_ACTION_ORDER:

1. Re-read live Product branch, PR #146, PR #147, DEV5 coordinator/directive, Drive handoff and RUN_STATE before mutation.
2. Canonical Product `3e15dc2e844cb825e482317fd024795130147011` remains HOLD; do not call READY_FOR_DEV5_INTAKE until both current privacy defect classes are repaired and exact-machine-GREEN.
3. Preserve PR #146 unchanged five-case PGN save/concurrency diagnostic oracle.
4. Preserve PR #147 unchanged three-case ImportRegistry diagnostic/batch privacy oracle.
5. Correct ImportRegistry repair boundary: use existing `acs/report_paths.py::report_safe_name()` (or equivalent shared sanitizer) only for user-facing error/report rendering. Preserve internal absolute paths required for fingerprint/reverification.
6. Preserve `SourceMutationError` and `SourceProvenanceError` classes and detection semantics; preserve `inspect_batch()` continuation/order semantics.
7. Correct PGN repair boundary: sanitize every path-bearing diagnostic proven in PR #146, not only outer save errors. Preserve no-clobber, expected-hash CAS, rollback and recovery-snapshot behavior.
8. After repair, first rerun exact strict oracles: PR #147 3 cases and PR #146 5 cases.
9. Then run import-registry/import-contract/ChessBase/PGN path/resource/concurrency/recovery/post-commit suites, relevant full unittest/pytest/diagnostic, and exact-head CI.
10. Keep ACSDB schema and canonical GameTree outside this repair unless a new strict reproduction proves a defect there.
11. Windows strict WIP=1 remains separate. Do not duplicate or weaken it and do not claim Ctrl+A/Ctrl+C Product defect without proof.
12. No force-push, skip, xfail or assertion weakening. `NVDA_VERIFIED=NO`.
