# DEV5_CURRENT_STATE

UPDATED_FROM_RUN: 20260823-1053
MODE: STAGE1_RELEASE_FREEZE / PRIVACY_REPAIR_MACHINE_GREEN / AUDIT_ACCEPTANCE_PENDING
SNAPSHOT_CUTOFF: 2026-08-23T10:53:41+03:00

Accepted Stage1 remains `0fa442330bc2bb03636ff9297512da4c29e38684` until independent Audit promotes a newer exact source. Persistent Full Product authority remains `dd9ebf9414103c805892856fe6a04706fa69039f` and is frozen during Stage1 release closure.

New release-critical fact: exact accepted Stage1 `0fa442...` has a machine-proven private-path diagnostic leak via QA PR #148. Related QA #146/#147/#149 proves the same class across PGN, ImportRegistry and Stockfish startup boundaries.

DEV5 repair candidate is PR #151 / `release/dev5-stage1-path-privacy-repair-20260823@909d8e2729e00ba5fce0f25a1520010844f9341b`. It is a direct descendant of exact accepted Stage1 and changes only report-path/error rendering plus its regression/workflow files. No chess/core/UI/QA-harness semantics are changed.

Exact run `32627213644` is terminal SUCCESS:
- Linux `97164249233`: Product privacy 6/6, unchanged independent privacy oracles PASS, unittest 659/659, pytest 737 + 758 subtests, SELFTEST + complete diagnostic PASS.
- Windows `97164249154`: privacy 6/6, Stage1 release contracts 75/75, unittest 659/659, pytest 737 + 758 subtests, SELFTEST + complete diagnostic PASS.

Classification: `MACHINE_GREEN_REPAIR_CANDIDATE / NOT YET ACCEPTED_STAGE1_AUTHORITY`.

Strict packaged UIA is still a separate release gate with classification `C — INCONCLUSIVE / synchronization-observability`, not a proven Ctrl+A/C defect. QA-owned helper is unchanged. No fresh ZIP exists.

DEV4 is currently terminal QA-only/Product-hold for the touching privacy evidence. DEV-B/DEV-C do not own a competing accepted-Stage1 repair at this cutoff. No Product overlap was violated.

Release state:
- FRESH_WINDOWS_CANDIDATE=NO
- READY_FOR_RELEASE=NO
- NVDA_VERIFIED=NO

PR #54/frozen refs untouched. Old rejected ZIP permanently ineligible.
