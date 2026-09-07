# Version 2 completion checkpoint

Branch: `codex/v2-formats-completion-20260907`, review #435.

## Verified work

Accepted format owners are composed, including Windows file ownership, PGN
Save/Save As, Library export, Books core/HTML/TXT/Markdown and Book-to-Board.
The exact owner ancestry is enforced by `scripts/verify_version2_composition.py`.
Do not reimplement these owners or ingest the competing umbrella #397.

The composition at f2cb570dba95c17fdc033b14a57833254d2ca194 passed Windows and Linux
jobs in run 34129250180. Real pinned HTML and TXT book oracles passed locally.

The next application checkpoint integrates accepted import observer #412 and
connects native PGN operations, detached Library game opening, exact import DTOs,
book navigation and persistent exact return. Empty import and immediate-worker
terminal ordering are repaired. Selected variation export uses canonical legality
and the existing atomic writer. Full local pytest: 1629 passed, 4 skipped.

## Continue here

1. Bind `Version2Application` to the real Windows UI thread, one shared action
   registry and the existing Stage 1 board/engine API. Preserve the original
   64-square DOM and Move input identity; no duplicate chess state.
2. Add the V2 WebView bootstrap and launcher, exercise actual Windows host and
   keyboard journeys, then build an exact-source candidate package.
3. Finish safe V1 data upgrade and large streaming PGN host integration.
   #403 still has an unsafe preservation race; do not mark it accepted or copy it.
4. Diagnose inherited owner-only workflow scope failures using the stronger
   composition proof, retaining their domain tests and corpus oracles.

No V2 distributable has been accepted. Human NVDA acceptance remains NOT RUN.
Legacy disabled Stage 1 build workflows and rejected ZIPs must stay untouched.
