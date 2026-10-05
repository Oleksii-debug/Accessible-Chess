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

## Next checkpoint: persistence/import and package composition

The current #1950 source at `c2da619b14445056215f2eed35f531994a805064`
is retained by a history-preserving merge into this candidate, without modifying
its owner branch. Read errors, malformed persisted data and write failures now
retain the original authority/bytes until explicit recovery; failed writes roll
back the shared registry identity and values. Its eight regressions pass locally.
The import-write test now confirms warnings and asserts the writer was actually
called: the older test could pass without ever reaching its injected I/O failure.

Blocking import conflicts now use a ValueError-compatible typed result from
the canonical registry. The UI gets localized structured duplicate/alias
diagnostics, not raw exceptions, and cannot force the conflict with warning
confirmation. New EN/UK tests prove unchanged shared identity, snapshot and
persisted bytes for both rejected binding and alias collisions.

Function-style tests are now explicitly executed by pinned pytest in CI;
`unittest` alone does not run them. Local direct execution of all 51 functions
in the selected composition/adapter/editor/service modules passed, including
tmp_path cases. The 55 unittest cases across ingress, warnings, corruption,
persistence and passive keybinding boundaries passed before the extra conflict
matrix was added; subsequent focused package/keymap/resource-order run passed
112 cases.

Full discovery completed on the earlier candidate: 4618 tests, 157 failures,
79 errors, 12 skips. This is NOT a full-suite pass. Many require isolated
attribution; e.g. old PGN journey fixtures pass PgnOpenResult where the accepted
application requires PgnDocumentSession, and other tests assert obsolete source
spellings or bypass newly-required confirmation. No runtime protection is
relaxed to accommodate these fixtures.

Package preparation and canonical tree/ZIP preflight now require the local
profile and P0 runtime scripts loaded by the actual launcher. Four negative
checks reproduced acceptance of missing scripts before this repair. Missing
resources now reject publication/readback, even after generic checksums are
regenerated. A dynamic contract records every actual launcher resource read
and requires it in both existing validators. No second package validator or
synthetic final artifact is introduced.

Sound-fixture repairs preserve the existing inventory hash checks: substitution
uses the same PCM width/byte size to reach SHA-256 rejection, and synthetic
semantic fixture counts follow the current SoundEvent set rather than a stale
literal nine. These tests do not identify or substitute the user's latest
332-file archive; that external archive remains unresolved.

## Actual Classes route keyboard coverage

A production-registry regression reproduced that all three `education_list`
keyboard actions were absent from the final composition, although its Classes
route composes EducationSurface. The preview registry tests alone missed this.
The final profile now includes only the three composed Education keyboard
actions, not the uncomposed Classroom preview actions. Both languages exercise
modifier remaps, restart/adoption, removal of old defaults and context reset.
The 19 Education/profile-ingress unittest cases passed locally. This remains a
source candidate, not Windows/NVDA or final-package acceptance.

## Bilingual integration and executable live-help coverage

The separately owned #1959 exact source
`a62e2e1e180cca21c51d013821bb249a45b0e209` is retained by a
history-preserving merge; its branch is not modified. Its policy and generic
WebView failure localization are consumed rather than recreated. A regression
covering both the actual final and full preview registry reproduced 155 missing
Ukrainian-label subcases. The existing canonical adapter catalog now supplies
all missing product labels; the eight bilingual contract tests pass. Translation
does not add remote or preview mutation actions to the production profile.

Three obsolete keyboard tests now execute the actual shipping shell resolver
and live Help function. They cover remapped board/submit labels in both languages,
unbound action removal, empty-snapshot clearing, and native editing/copy guards;
all three Node scripts pass. The plain UTF-8 owner guide now documents all 79
fallback actions, current remapping/recovery and composed toolbar/Education/profile
defaults without presenting Classroom preview as the final Classes route.
All six owner-document tests pass, including executable keyboard coverage.
The combined 40-case qualification/localization/docs/Education/ingress run passes.
The previous broader full-suite failure remains unresolved, not overwritten by
these focused results.
