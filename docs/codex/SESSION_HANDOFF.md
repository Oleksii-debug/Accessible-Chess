# Codex autonomous session handoff — DEV4 QA/evidence

Checkpoint date: 2026-08-23.

Lane branch: `codex/qa-evidence-20260821`.

This run operated in SAFE OVERLAP and made no Product mutation. Windows WIP=1 was respected.

Live combined Stage1 line at read: `release/dev5-stage1-combined-repair-20260823@574d8c7344a7490de46ba38498f363395c951019`. Product delta over `80720e8125c59a213f278668d599040f2768d553`: `acs/history.py` and `acs/stockfish_runtime.py` only.

Latest strict packaged evidence inspected: PR #175, run `32636245736`, exact packaged Product `1e9d23b034e6d347fe03c3581469a07e16037c55`.

Machine evidence before failure: full exact-source regressions, long-history/atomicity, engine lifecycle, path privacy, native menu structural gate, standalone build, built-EXE diagnostic and real WebView2 startup passed. Strict packaged UIA then proved Backspace, Ctrl+A selection and Ctrl+A/Ctrl+C clipboard behavior PASS. It subsequently failed retained semantic board-focus continuity after the pure submit bridge because final UIA focus remained on `automation_id='move-input'`, name `Хід`.

Finding classification:
- `PROVEN_PRODUCT_DEFECT` on exact packaged `1e9d23b...`: board-focus continuity after submit bridge.
- Ctrl+A/Ctrl+C: PASS, not a defect.
- `HUMAN_ONLY`: native menu Alt/Arrows/Enter/Esc + NVDA usability.
- exact combined `574d8c7...` packaged focus behavior: not yet run/proven.

Durable publication: AUTOPULSE Issue #177 comment `5385891066` plus `docs/codex/lanes/QA_EVIDENCE.md`.

Release state: `FRESH_WINDOWS_CANDIDATE=NO`; `READY_FOR_RELEASE=NO`; `NVDA_VERIFIED=NO`.

Exact next action: after combined validation/audit and when Windows WIP=1 is free, run one fresh strict packaged candidate chain on the exact accepted combined SHA with all current Ctrl+A/C and semantic-focus assertions preserved. If the focus failure reproduces, route minimal UI Product repair to D01/current UI owner rather than weakening QA.
