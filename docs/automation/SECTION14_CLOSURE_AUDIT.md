# SECTION 14 CLOSURE AUDIT — Windows application, keyboard, menu, settings, languages, sounds and clocks

Canonical plan section: **SECTION 14 — Windows application, keyboard, menu, settings, languages, sounds і clocks**.

Exact predecessor: Section 12 terminal integration `642550032df0ee29f04df59816504e91f62298c8`.
Section 13 dependency is preserved byte-identically on this predecessor for:
`acs/engine.py`, `acs/stockfish_runtime.py`, `acs/analysis_service.py`,
`acs/continuous_analysis.py`, `acs/ui_analysis_adapter.py`,
`acs/engine_play_service.py`, and `acs/engine_game_session.py`.

This finisher is intentionally evidence/gate-only. The accepted predecessor already contains the required Product implementation; creating a second Windows, keymap, language, sound, settings or clock authority would violate the canonical architecture.

## 14.1 One-click standalone Windows application

Accepted authorities:
- `packaging/portable_launcher.c`: native x64 GUI launcher using the Windows subsystem.
- `acs/version2_portable_package.py`: canonical one-click outer package with root `AccessibleChess.exe` and packaged `App/AccessibleChess.exe`.
- `acs/version2_package_preflight.py`: forbids raw source extensions in the public package and requires exactly one canonical Product executable plus the standalone desktop runtime closure.
- `.github/workflows/p0-user-oneclick-portable-launcher.yml`: builds the native launcher and exercises real-window, timeout, duplicate-launch and early-failure behavior.
- package/launcher regression suites: `tests/test_portable_launcher_contract.py`, `tests/test_portable_launcher_window_readiness.py`, `tests/test_version2_portable_package.py`, `tests/test_version2_package_preflight.py`, `tests/test_v2_package_required_resources.py`.

The user launches a Windows EXE; no installed Python interpreter or command-line workflow is required. The package may contain its private embedded runtime, but raw application source is forbidden by preflight.

## 14.2 Native Windows menu, predictable keyboard/focus and remappable shortcuts

Accepted authorities:
- `acs/keybindings.py`: one `ActionRegistry`/context model, collision detection, reserved-key warnings, remap/reset/help and persisted profile load/save.
- `acs/full_product_native_menu.py`: native Windows menu is projected from the same ActionRegistry and refreshes captions from live bindings.
- `acs/version2_release_ui.py`: native and WebView paths route through the same command authority and preserve focus.
- regression suites: `tests/test_keybindings.py`, `tests/test_keybindings_persistence_boundary.py`, `tests/test_full_product_native_menu.py`, `tests/test_version2_release_accessibility_contract.py`, `tests/test_dev1_release_ui_regressions.py`.

No second shortcut or command registry is introduced by this closure.

## 14.3 UA/EN through one canonical language system

Accepted authorities:
- one persisted `settings.language` value, validated to `uk` or `en`;
- `UILanguage`/Version 2 language owner synchronizes Stage 1, Version 2 projections and the native menu;
- language changes preserve route/focus/chess state and roll back atomically on persistence or host-refresh failure;
- regression suites: `tests/test_w6_v2_language_owner_current.py`, `tests/test_stage1_localized_validation_current.py`, `tests/test_version2_release_accessibility_contract.py`.

The closure does not create a parallel translation state.

## 14.4 Gameplay sounds, packs/profiles/settings, event mapping, mute/volume

Accepted authorities:
- `acs/settings.py`: canonical persisted sound enable, volume, clock/low-time policy and per-event variant settings.
- `acs/sound_events.py`: semantic chess-to-sound event policy.
- `acs/sound_runtime.py`: deterministic event queue, master disable/zero-volume mute, volume forwarding and isolated adapter failures.
- packaged sound resolver/Windows adapter plus canonical inventory/provenance validation in package preflight.
- user sound-pack builder with bounded/validated 330-WAV archive support.
- regression suites: `tests/test_sound_runtime.py`, `tests/test_user_sound_pack_builder.py`, `tests/test_stage1_release_composition_ui.py`, `tests/test_settings.py`.

Sound is presentation only and never becomes chess truth.

## 14.5 Chess clocks/timers and accessible result/error feedback

Accepted authorities:
- `acs/clock_service.py`: one deterministic `ChessClock`/`TimeControl` authority with start/pause/resume/stop/switch/increment/flag/restore/recovery behavior.
- engine/local UI uses that clock authority and serializes board/lifecycle/clock acceptance.
- concise localized result/error paths avoid Python/provider leakage.
- clock/sound UI projection exposes user and opponent time plus low-time/tick policies without creating a second game authority.
- regression suites: `tests/test_clock_service.py`, `tests/test_clock_engine_serial_acceptance.py`, `tests/test_stage1_engine_play_ui.py`, `tests/test_stage1_complete_user_flow.py`, `tests/test_stage1_release_composition_ui.py`.

## Dependency and architecture readback

The exact Section-12 predecessor carries all seven Section-13 runtime blobs byte-identically to terminal Section-13 merge `ca3ba2c6379fda30cd438dcc339efed2d663cfd2`. Section 14 therefore sits on the accepted local workflow while preserving the accepted Stockfish/analysis/engine-game implementation.

## Qualification

The dedicated workflow `Section 14 Windows Application Terminal Gate` runs the mature acceptance suites above on Ubuntu and Windows. Under Simplified Section Closure Protocol v3:
- any executed failing gate is a blocker;
- hosted jobs that remain queued/unstarted because runners are unavailable are recorded as infrastructure unavailability, not GREEN;
- missing manual NVDA evidence is final whole-product acceptance, not an intermediate Section blocker.

No additional Product mutation is required for the fixed Section-14 contract.
