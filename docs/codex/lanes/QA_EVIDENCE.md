# Codex lane — QA / Evidence / Security

Owner: DEV4 independent QA/evidence/security lane.

Start branch: `codex/qa-evidence-20260821`.

## 2026-08-23 live checkpoint

Mode: SAFE OVERLAP. Windows strict WIP=1 respected; no duplicate candidate run launched. Product implementation ownership remains outside this QA lane.

Current combined Stage1 repair line at live read: `release/dev5-stage1-combined-repair-20260823@574d8c7344a7490de46ba38498f363395c951019`. Its Product delta from `80720e8125c59a213f278668d599040f2768d553` is limited to `acs/history.py` and `acs/stockfish_runtime.py`; no UI/focus Product surface changes.

Fresh strict packaged evidence from PR #175 run `32636245736` on exact Product `1e9d23b034e6d347fe03c3581469a07e16037c55`:
- exact-source/full regressions, long-history/atomicity, engine lifecycle, privacy, native menu structure, standalone build, built-EXE diagnostic and real WebView2 startup passed before the strict cross-process UIA failure;
- native Move Edit Backspace control passed;
- native Ctrl+A selection passed;
- native Ctrl+A/Ctrl+C clipboard behavior passed; do not claim a Product Ctrl+A/Ctrl+C defect;
- strict semantic focus then failed after the pure submit bridge: final UIA focus remained on `automation_id='move-input'`, name `Хід`, instead of converging back to the board.

Classification:
- `PROVEN_PRODUCT_DEFECT` on exact packaged `1e9d23b...`: board-focus continuity after submit bridge fails the retained cross-process semantic-focus contract despite source-level focus tests being green; this is a false-green boundary in source-only evidence.
- Current combined `574d8c7...` is focus-surface-equivalent but has not itself been packaged through strict UIA, so exact-SHA reproduction there remains required before attributing a machine failure to that SHA.
- `HUMAN_ONLY`: Alt/Arrows/Enter/Esc native-menu usability with NVDA.
- `NVDA_VERIFIED=NO`, `FRESH_WINDOWS_CANDIDATE=NO`, `READY_FOR_RELEASE=NO`.

Durable cross-lane publication: AUTOPULSE control Issue #177 comment `5385891066`.

Next highest-value independent check: after combined source validation/audit and when Windows WIP=1 is free, preserve the existing strict Ctrl+A/C and semantic-focus assertions and run one exact combined packaged chain. If focus reproduces, route a minimal Product repair to D01/current UI owner; never weaken the QA assertion.

Mission: independently stress current implementation and future packages with behavioral, adversarial, security, import/package and regression evidence. Prefer new tests/tools/evidence files and avoid competing implementation edits with Stage1/full-product agents.

Do not weaken or delete failing gates. Do not claim human NVDA verification. Do not run duplicate strict Windows candidates; WIP=1 applies. A hypothesis is not a Product defect until reproduced independently of the QA harness.

Priority areas: current red CI root causes, false-green tests, long history/variation/FEN/editor sequences, engine concurrency/lifecycle, sound failure isolation, keymap/search/menu semantics, security/path/injection checks, package/resource assumptions, PGN/ACSDB/ChessBase round-trip/data-loss tests as those subsystems advance.

At every durable checkpoint append/update this file with:
- UTC timestamp;
- exact branch/SHA;
- exact commands and results;
- defects classified PROVEN_PRODUCT_DEFECT / QA_OR_ENVIRONMENT_ONLY / INCONCLUSIVE / HUMAN_ONLY;
- new regression tests/evidence;
- exact affected branch/SHA owned by another lane;
- next highest-value independent check.
