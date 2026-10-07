# Section 9 closure audit — real refreshable tactile hardware adapter

Status target: **DONE / terminally skipped for ordinary workers** after exact-head qualification and durable GitHub closure.

## Canonical scope

Section 9 requires a real refreshable tactile graphics adapter, connect/disconnect plus capabilities/geometry/status/errors/settings, fail-safe rendering with simulator parity, a strict adapter-vs-chess-core boundary, and non-blocking behavior when no physical device is present.

## Implemented device choice

The implementation uses **DotPad** as the plan-authorized real refreshable tactile graphics device. `CtypesDotPadSdkApi` in `acs/tactile_dotpad_sdk.py` binds only the documented official Windows SDK C surface and loads it lazily. Vendor DLLs are not committed to this repository.

Official contract references used for the adapter boundary:

- Dot Developer portal: https://developer.dotincorp.com/en
- DotPad Windows SDK guide: https://github.com/dotincorp/dotpad-sdk-guide/tree/main/Windows/3.0.0
- Windows SDK C header: https://github.com/dotincorp/dotpad-sdk-guide/blob/main/Windows/3.0.0/DotSDKAPI.h

The bound calls are `DOT_PAD_CONNECT_SERIAL`, `DOT_PAD_CONNECT_BLE`, `DOT_PAD_GET_CONNECTED_DEVICE_COUNT`, `DOT_PAD_GET_CONNECTED_DEVICE_HANDLE`, `DOT_PAD_GET_DISPLAY_INFO`, `DOT_PAD_DISPLAY_DATA`, `DOT_PAD_RESET_DISPLAY`, and `DOT_PAD_DISCONNECT`.

## Acceptance map

### 9.1 Real adapter

`DotPadTactileAdapter` drives the official DotPad SDK through `CtypesDotPadSdkApi`. The SDK is dynamically loaded only when hardware output is configured, so normal Accessible Chess startup does not depend on a tactile device.

### 9.2 Device lifecycle and diagnostics

- `DotPadSettings`: serial/BLE choice, endpoint, optional SDK path, bounded connection timeout, clear-on-disconnect policy.
- `connect()` / `disconnect()` / `close()` are explicit and idempotent at the adapter boundary.
- `TactileCapabilities` reports provider, connection, graphics/braille support and discovered pin geometry.
- `TactileDeviceStatus` reports connection state, device count, geometry and stable error detail.
- `TactileAdapterErrorCode` supplies stable machine-readable failures.

### 9.3 Fail-safe rendering and simulator parity

`TactilePinFrame` is an immutable pin-only handoff. `encode_dotpad_graphics()` converts each 2x4 pin cell to the standard eight-dot byte layout and rejects geometry mismatches before device output. A rejected/failed render resets the graphics display and never publishes a partial success. `DotPadSdkSimulator` implements the same narrow SDK surface for deterministic parity tests.

### 9.4 Adapter is not chess core

The three device modules import no chess, Position, GameTree, PGN or engine authority. Tests parse all three module ASTs and reject chess-rule imports. The adapter accepts only an already-rendered pin frame; it cannot make moves, validate positions, navigate a game tree or mutate chess state.

### 9.5 No physical device is not a product blocker

Importing the module is safe on non-Windows hosts. The SDK is loaded only when `CtypesDotPadSdkApi` is instantiated. Missing Windows support, missing SDK DLL, missing device, timeout and render failure are bounded adapter errors rather than process-wide failures. Automated acceptance therefore uses the deterministic SDK simulator; physical DotPad and owner/NVDA handling remain final whole-product acceptance evidence under Simplified Section Closure Protocol v3.

## Automated evidence

`tests/test_section9_dotpad_tactile_adapter.py` covers:

- serial and BLE settings;
- all eight dot-bit mappings;
- geometry rejection;
- connect/capabilities/status/render/clear/disconnect;
- serial/BLE simulator parity;
- fail-safe reset after render rejection;
- clear-on-disconnect;
- deterministic connection timeout;
- disconnected-render rejection;
- safe import without Windows/device;
- no chess-core imports;
- exact official SDK symbol binding.

`.github/workflows/section9-dotpad-tactile-adapter.yml` runs compile + contract tests on Ubuntu and Windows for the exact PR head.

## Reopen rule

After durable DONE, ordinary workers must not re-enter Section 9. Reopen only for a concrete regression, invalid closure evidence, a materially changed Section-9 acceptance contract, or later integration that demonstrably breaks this adapter.
