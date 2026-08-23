# DEV4 Stage1 Stockfish runtime privacy repair

Exact parent: `80720e8125c59a213f278668d599040f2768d553` (DEV5 PR #151).

Independent DEV3 QA PR #159 proved that `resolve_stockfish_path()` leaked private workstation/application parent directories in missing configured, missing packaged, and empty/corrupt executable diagnostics on both Ubuntu and Windows while the existing Stockfish runtime suite remained green.

This narrow repair changes only the user-facing resolver diagnostics in `acs/stockfish_runtime.py` and reuses the accepted `report_safe_name()` boundary. The internal resolved `Path` returned for a valid executable, configured-path authority, packaged-relative resolution, exception classes, exception chaining, provider ownership, and engine lifecycle are unchanged.

The copied `tests/test_dev3_stockfish_runtime_path_privacy.py` is byte-for-byte the independent PR #159 oracle. Do not weaken it.

No accepted Stage1 ref, QA strict UIA helper, candidate ZIP, or NVDA status is changed here.

`READY_FOR_STAGE1_PROMOTION=NO` until exact Linux+Windows validation is green and DEV5/AUDIT accepts the repair.
`FRESH_WINDOWS_CANDIDATE=NO`
`NVDA_VERIFIED=NO`
