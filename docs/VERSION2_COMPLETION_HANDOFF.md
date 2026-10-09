# Version 2 completion checkpoint

Current runtime: `codex/v2-runtime-completion-20260907`, review #441.
Parent formats integration: #435.

## 2026-09-08 native UI thread checkpoint

Base is live `8802785fbd38f10b8431b5069dcb2931472c7a81`, preserving W5's
refreshed formats composition. No recovery-tree replacement was performed.
The earlier 1646-test tree at `4e8e7ce4617544a2788eec68e3ef7353bba9c168`
remains UNINTEGRATED and must not replace this newer runtime.

Reproduced a production failure: a real `Version2Application` bound to the API
rejects `v2_snapshot` when called from a WebView worker. The bounded repair
constructs the application's SQLite connection on the actual native Form thread
and marshals both the inherited board API and V2 public methods through that
same owner. Native file runtime construction and application shutdown also stay
on that thread. Canonical SQLite/application/W3 thread guards remain unchanged.
The eager factory contract remains available for headless diagnostics; the
production launcher explicitly requests deferred native construction.

Local full pytest: **1710 passed, 4 existing skips**. New real-state regressions
exercise concurrent bridge-like calls, Library search, PGN editing, inherited
board commands, disposed-owner rejection and deferred database construction.
Compile and diff hygiene pass. The new `V2 Native UI Thread Runtime` Windows
workflow exercises the actual WebView2/JS bridge, native MenuStrip, SQLite and
import worker/mailbox; its result must be read from CI, not inferred locally.
Its trusted source-picker fixture is NOT human/native-picker UI evidence.

Pending integration remains owned: #536 external PGN/Book review isolation,
#560/#543 ordered browser refresh, #534 large PGN host import, #503 keymap
convergence, #476/#498 startup cleanup, #491 language, #507/#514 real diagnostic
and executable build, and the existing package/UIA owners. Do not duplicate.
W5 requires terminal combined Formats + Windows Composition before successor
intake. On 8802785 Windows Composition passed (34201473141), but no broad
Formats run was present; trigger coverage was routed to W5/#467 in #441.

No Windows ZIP exists from this checkpoint. NVDA_VERIFIED=NO.

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
3. Finish current successor integration and large streaming PGN host integration.
   The older #403 race warning is superseded: current tracked-writer repair is
   already composed in 8802785 and its upgrade workflows pass. Do not restore
   an older upgrade blob or reopen that old finding without new evidence.
4. Diagnose inherited owner-only workflow scope failures using the stronger
   composition proof, retaining their domain tests and corpus oracles.

No V2 distributable has been accepted. Human NVDA acceptance remains NOT RUN.
Legacy disabled Stage 1 build workflows and rejected ZIPs must stay untouched.
