# Owner Windows build continuation — 2026-10-06

Requested outcome: current compiled Windows application with the existing original owner sound set, delivered in chat and Drive.

## Exact inputs and work

- Source checkpoint: `6be0afe67366b62757baae53ab0eaae6b8bfafdf`, canonical shipping PR #2184; includes merged owner gameplay PR #2195.
- Local branch: `build/owner-windows-20261006-6be0afe`.
- Added compiler-input workflow using the existing pinned Nuitka/Windows runtime toolchain. It produces intermediate inputs, not an accepted release; canonical assembly/preflight remains required.
- Added repeatable `python -m scripts.probe_owner_sound_payload SOUND_DIRECTORY [--native]` probe. It validates the existing inventory and exercises all sound variants plus production new-game/e4/e5/nf3 delivery. Default mode observes the final platform port on Linux; native mode is Windows-only.
- Reused all existing 330 WAV files; no repeated download and no private sound bytes committed.
- Prior compiled app is source `25b6da6eb8bccea95628ecfce5ba81fece1a5666`; it must not be represented as rebuilt current code.

## Verified

- Python: 77 tests run, 76 pass, one Windows-native playback test skipped on Linux. Suites: owner_gameplay_feedback, owner_gameplay_wav_delivery, sound_events, sound_runtime, user_sound_pack_builder.
- Full-product production composition diagnostic passes; Python compileall passes.
- Owner gameplay keyboard and late-bridge sound-settings DOM suites pass.
- Actual original pack: 330 file sizes/digests and PCM structures verified; 12 events, 37 variants, 49 variant adapter calls; new game plus three moves deliver 7 non-silent layered playback calls at default volume 80.

## Open findings and blockers

- `tests/js/library_surface_dom_test.js` fails at `date search did not dispatch`. Current implementation adds serialized Promise dispatch; the test waits only one microtask and also expects concurrent searches. Do not claim this suite passes; reconcile its oracle with serialized command semantics before full qualification.
- Original optional `library/Russian/Draw.wav` contains zero PCM samples. Default draw uses `library/Server/Gong.WAV` and is non-silent. Original source files are preserved.
- Automatic approval review rejected the git push that would publish the new branch/workflow and launch Windows compilation. Stated reason: publishing a new workflow/branch is a persistent remote mutation beyond its interpretation of the build/package authorization. No workaround or retry performed. Explicit approval is needed for this concrete publication/compilation action.
- No Actions run exists for the local build branch at this checkpoint. Native compilation has NOT started.
- HUMAN_TESTED=false; NVDA_VERIFIED=false; AUDIBLE_WINDOWS_VERIFIED=false; NEW_WINDOWS_ZIP=false.
- Excluded from git: private sound/archive bytes, previous binaries, runtime caches, private logs, credentials and keys.

## Next action

After explicit permission to publish the prepared GitHub build branch and run Windows compilation: push this branch, consume the Windows compiler result, assemble using canonical package validation, run packaged diagnostics, then upload the resulting verified test ZIP to chat and Drive. Do not deliver the old executable as the new build.

## Authorization update

The owner explicitly approved publishing this build branch and running Windows compilation on 2026-10-06. Direct git push subsequently failed because the shell has no GitHub credential helper. Continue publication through the existing authenticated GitHub connector.
