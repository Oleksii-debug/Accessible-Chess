# Codex lane — QA / Evidence / Security

Owner: Codex QA/evidence agent.

Start branch: `codex/qa-evidence-20260821`.

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