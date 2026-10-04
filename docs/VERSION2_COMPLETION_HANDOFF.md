# CURRENT Version 2 convergence checkpoint — 2026-10-04

This section is the authoritative continuation checkpoint. Historical checkpoints
below remain provenance only when they conflict with this section.

Canonical Full Product branch:
`work/full-product-teacher-education-reachability-20260911`

Canonical Full Product SHA:
`0a92698bbb923ef6d7bc2d672e3fd30554fb0138`

Whole-product convergence PR: #1558
`converge/full-product-final-20261004`

Current rollup lineage before this documentation-only successor:
`ea6deef667fa64bd3cfbf511ca2c368f7dc0dcb2`

Integrated semantic apex retained as ancestry:
#1570 `00d89fd48e4e60389ef7298958500d2a29d956ce`

Direct Product -> rollup geometry is ahead-only / behind=0 with merge-base equal
to exact canonical Product. #1558 is mergeable and remains DRAFT while exact-head
qualification is nonterminal.

## Integrated authority

The rollup contains the current convergence chain rather than parallel
reimplementations:

- BookDocument live semantic validity from #1561;
- PGN move-number/SAN structural integrity from #1562;
- HTML reading-order, hidden-content and text-boundary safety from #1563;
- canonical Book variation FEN equivalence from #1564;
- Library recovery-warning provenance for Book references from #1565;
- BookIndex canonical Unicode/whitespace search, full ListBlock search and
  detached immutable index snapshot from #1567;
- Markdown heading/image/fence/list/recovery safety from #1570;
- retained evidence-gated Windows-1251 decoding across current text/HTML paths;
- the prior Full Product Books/Training/Library/recovery/accessibility line,
  including PGN modifier-key delegation and Ukrainian owner/NVDA documentation.

The current Product authority still owns chess rules, canonical PGN/GameTree,
persistence, Library, Book/Training runtime and package assembly. Do not create
a second parser, rules engine, Book navigation model, persistence model or
package validator to continue this checkpoint.

## Qualification authority

The #1558 `Full Product Convergence 2026-10-04` gate now qualifies both Ubuntu
and Windows and explicitly executes:

- BookDocument, BookIndex and BookReader;
- GameTree and D06 PGN round-trip;
- HTML semantic/head metadata;
- EPUB import and package contract;
- Book canonical Game/FEN and Library-reference reconstruction;
- TXT/Markdown plus semantic-list regressions;
- Books/Training and Library browser/application regressions;
- Settings/recovery/writer-race regressions;
- Ukrainian owner accessibility documentation;
- package assembler, package preflight/hardening, required resources,
  ZIP-topology, release payload and release diagnostic composition;
- DOM checks, `run_accessible_chess_v2.py --diagnostic` and `acs.selftest`.

BookDocument and PGN component gates have explicit whole-product inherited modes:
narrow owner PRs still require exact owner-only scope, while the #1558 rollup
pins the exact reviewed owner blobs and integrated-apex ancestry instead of
false-failing because Product -> rollup is intentionally broad.

At this checkpoint GitHub Actions are registered but queued/pending because
runner capacity is saturated. QUEUED/PENDING is not GREEN. Do not merge #1558
or claim acceptance from historical green runs.

## Remaining acceptance gates

- HUMAN_TESTED=NO
- NVDA_VERIFIED=NO
- FINAL_WINDOWS_ZIP=NO

Physical Windows 11 + NVDA keyboard acceptance remains required. A final Windows
ZIP must be produced only through the canonical Version 2 package
assembler/preflight/release-payload path after exact-head CI is terminal green.
Do not substitute an older ZIP or an ad-hoc archive.

## Continue from here

1. Treat #1558 current head as the integration authority and #1570 ancestry as
   the latest semantic source apex; do not restart a broad audit.
2. Read exact-head #1558 Actions. Repair real RED failures before adding product
   scope. Ignore stale historical runs as qualification evidence.
3. Keep source component PRs/branches until rollup qualification is complete;
   they are provenance, not competing product heads.
4. When exact-head CI is terminal green, run canonical package
   assembler/preflight/readback and preserve the artifact identity.
5. Perform the physical Windows/NVDA keyboard journey against that same packaged
   candidate, record evidence, and only then mark the product accepted.

---

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
