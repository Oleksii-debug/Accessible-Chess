# Section 37 terminal closure candidate

Date: 2026-10-09  
Canonical finisher: PR #2512, `integrate/section37-preserve-tested-corpus-sources-20261009`  
Qualified implementation candidate: `3e2f816a3a47c7532c246af6e5d585030e587392`

## Acceptance result

Sections 37.1–37.6 are repository-complete on the candidate. The terminal gate is
`tools/section37_closure_gate.py`; its deterministic receipt is
`docs/corpus/SECTION37_TERMINAL_CLOSURE_EVIDENCE.json`.

- 37.1: 24-entry canonical registry plus 69-entry supplemental source catalog;
  source page, acquisition state, authorship, format, checksums, size limits and
  read/test/redistribute boundaries are explicit and fail closed.
- 37.2: checked-in original PGN, EPD/FEN ZIP, Lichess ECO TSV, annotated-game,
  puzzle and historical-study sources are checksum-pinned and semantically read.
- 37.3: Capablanca original text completes canonical import/restart; three more
  GITenberg originals are bound to exact commits/raw Git blobs. Bird and Fishburne
  complete canonical import/restart. Staunton is correctly retained as an
  unsupported ISO-8859 semantic-import result, not transcoded into a false PASS.
- 37.4: real CBV→CBH→ACSDB readback is 113/113 against an independent PGN oracle
  with 14 CBH-family companions. Real external CBH source-family inventories are
  pinned. CBF+CBI, complete 2CBH and CBONE remain explicitly documented unavailable;
  the canonical plan requires that documentation and does not authorize fabricated,
  paywall-bypassed or falsely successful fixtures.
- 37.5: source and shipped-package separation remains protected and release
  exclusion tests reject uncleared originals even when renamed or nested.
- 37.6: bounded acquisition, exact identity/checksum checks, safe ZIP handling,
  temporary-source cleanup and recovery/restart evidence remain protected.

## Executed qualification

On candidate `3e2f816a3a47c7532c246af6e5d585030e587392`:

- Section 37 authenticity, rights, negative, archive, recovery and readback suite:
  **56/56 PASS**, zero skips, using three independently checked-out pinned
  GITenberg repositories.
- `python tools/section37_closure_gate.py` regenerated the committed terminal
  receipt byte-for-byte.
- `python -m acs.selftest`: **PASS**.
- JSON validation, Python compilation and `git diff --check`: **PASS**.

An adjacent 138-test diagnostic was also executed. Eight failures reproduced
identically on untouched `origin/main`: five cancellation-harness failures caused
by this container's symlinked `sys.executable`, and three existing BookProgressStore
race-oracle result differences. They are not represented as green, were not caused
by the Section 37 diff, and are outside this Section's bounded qualification.

## Rights and release boundary

Terminal closure qualifies sources and provenance; it does not transfer rights.
Third-party originals without explicit redistribution clearance remain TEST_ONLY
or external-ephemeral and are excluded from PUBLIC_RELEASE. Proprietary formats
are never auto-downloaded or fabricated.

