# Codex current state — DEV4 QA/evidence — 2026-08-23

Live GitHub technical truth supersedes the older 2026-08-21 snapshot formerly stored in this file.

## Current Stage1 authority transition

- Prior accepted Product source exercised by the latest strict packaged run: `1e9d23b034e6d347fe03c3581469a07e16037c55`.
- A later independently accepted DEV2 repair for oversized history targets means `1e9d23b...` is no longer eligible as the final human candidate source.
- Current combined repair branch at live read: `release/dev5-stage1-combined-repair-20260823@574d8c7344a7490de46ba38498f363395c951019`.
- Combined Product delta over `80720e8125c59a213f278668d599040f2768d553` is only `acs/history.py` plus `acs/stockfish_runtime.py`; other delta paths are repair regressions/workflow.
- Combined validation workflow exists at that head, but no pull-request-triggered workflow run was associated with `574d8c7...` at this read. Do not call the combined line Audit-accepted or candidate-ready until live validation/audit says so.

## Latest strict packaged Windows evidence

PR #175 exact packaged Product: `1e9d23b034e6d347fe03c3581469a07e16037c55`.
Workflow run: `32636245736` — FAILURE at strict packaged cross-process UIA.

Before the failure, exact-source full regressions, long-history/state atomicity coverage, engine lifecycle/race coverage, path privacy, native menu structural gate, standalone build, built-EXE diagnostic and real WebView2 startup passed.

The strict gate decisively proved native Move Edit behavior:
- Backspace key delivery/control: PASS;
- Ctrl+A selection behavior: PASS;
- Ctrl+A/Ctrl+C clipboard behavior: PASS.

Do not claim Ctrl+A/Ctrl+C Product defects.

The retained semantic-focus assertion then failed after the pure submit bridge: UIA focus remained on `automation_id='move-input'`, name `Хід`, rather than converging back to the board.

Classification: `PROVEN_PRODUCT_DEFECT` on exact packaged `1e9d23b...` for board-focus continuity after submit bridge. Source-level focus contracts had been green, so this is also a source-only false-green boundary. The combined `574d8c7...` line has unchanged UI/focus Product surfaces, but must still reproduce the packaged failure on its own exact candidate before the defect is attributed to that exact SHA.

## Release state

`FRESH_WINDOWS_CANDIDATE=NO`
`READY_FOR_RELEASE=NO`
`NVDA_VERIFIED=NO`

Native menu Alt/Arrows/Enter/Esc usability with NVDA remains `HUMAN_ONLY`.

Windows strict WIP=1 remains mandatory. No duplicate strict run was launched by DEV4.

## Durable publication

DEV4 cross-lane finding published to AUTOPULSE control Issue #177 as comment `5385891066` and recorded in `docs/codex/lanes/QA_EVIDENCE.md`.
