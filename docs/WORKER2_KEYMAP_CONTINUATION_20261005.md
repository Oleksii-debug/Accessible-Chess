# Worker 2 continuation — not final-product acceptance

This continuation repairs the same serial #1956 → #1960 → #1961 candidate.
It does not promote main, a Windows package, or human/NVDA acceptance.

## Repairs and reproduced evidence

- PGN's inherited modifier guard rejected `Ctrl+J` before the live toolbar
  resolver. The new DOM test failed on that precise behavior before the repair.
- PGN now resolves modifier chords before dispatch and updates roving tabindex
  on pointer/programmatic focus as well as keyboard movement.
- PGN, Books and Training tests execute the actual `web/index.html` chord and
  context resolver. Coverage includes all four navigation actions, Ctrl/Alt/
  Shift/Win modifiers, disabled controls, stale defaults, native Enter/Space/
  Tab/Escape and Ctrl+C, synchronous cancellation, missing/not-ready resolver,
  and ready-empty/invalid resolver results.
- Toolbar actions belong to the base V2 registry as well as final-product V2:
  both roots actually compose the affected toolbars. Both profiles now have
  persisted modifier-remap/restart/context-reset regressions.
- `full_product_classroom.js` is a separate management preview, not the
  Classes surface composed by the final launcher. Its remaps remain in the
  full-product preview registry; production Settings no longer offer these
  uncomposed actions. The production Classes route uses EducationSurface.
- The actual launcher uses `version2_upgrade_status_release`, whose resource
  provider includes `version2_local_profile.js`; profile-name remapping remains
  a composed action there. This is source-composition evidence, not proof of
  an installed Windows artifact.
- The inherited terminal DOM test joined extracted source with literal `\\n`,
  preventing execution. It also had context-bound mocks and omitted the newer
  recovery helper. These harness errors are repaired without removing its
  keyboard, cancellation, localized-search, or focus-restoration assertions.
- Valid profile-ingress tests now exercise warning confirmation explicitly;
  risky default shortcuts are not silently accepted to make the tests pass.
- Existing core/DOM gates now test exact PR-head bytes and execute the added
  surfaces. D01 gates retain legacy identities and admit only paired exact
  current successor blobs; unknown identities still fail.
- Recovery qualification freezes/proves the original three-path source at
  `4707e3cbbd2bb33405320162481198ad4ce06293`, retains it in ancestry, and tests
  recovery behavior on each broader successor head instead of falsely requiring
  every subsequent shared-document PR to change exactly those three paths.

## Local checkpoint

Passed: 23 profile/ingress unittest cases, four executable qualification
contracts, PGN and Books/Training DOM suites, local-profile and preview-Classroom
DOM suites, terminal keymap and recovery DOM suites, and core selftest.

The broader warning-import tests exposed a separate defect: blocking duplicate
conflicts are rejected but their structured diagnostics are discarded before
the import confirmation boundary. This is still open at this checkpoint.
Full unittest discovery was launched and is not recorded as a pass.

Further actionable work includes merging the separately owned #1950 persistence
repair into a tested candidate without recreating it, restoring structured
blocking-import diagnostics, and enforcing all launcher-loaded resources in
the package validator (local-profile/P0 resources need explicit coverage).

IMPLEMENTED=YES
INTEGRATED=OPEN_SERIAL_CANDIDATE_ONLY
HUMAN_TESTED=NO
NVDA_VERIFIED=NO
FINAL_WINDOWS_ZIP=NO
