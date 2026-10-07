from __future__ import annotations

"""Real DotPad refreshable-tactile hardware adapter for Accessible Chess.

This module is intentionally device-only. It contains no chess rules, Position,
GameTree, PGN, or navigation authority.
"""

import time

from .tactile_dotpad_contract import (
    DotPadSdkApi,
    DotPadSettings,
    TactileAdapterError,
    TactileAdapterErrorCode,
    TactileCapabilities,
    TactileDeviceStatus,
    TactileGeometry,
    TactilePinFrame,
    encode_dotpad_graphics,
)
from .tactile_dotpad_sdk import CtypesDotPadSdkApi


class DotPadTactileAdapter:
    """Connect/disconnect/capabilities/status/settings and fail-safe rendering."""

    def __init__(self, settings: DotPadSettings, *, sdk: DotPadSdkApi | None = None) -> None:
        if type(settings) is not DotPadSettings:
            raise TactileAdapterError("DotPad settings are invalid", code=TactileAdapterErrorCode.INVALID_SETTINGS)
        self._settings = settings
        self._sdk = sdk if sdk is not None else CtypesDotPadSdkApi(settings.sdk_path)
        self._handle: int | None = None
        self._cell_width: int | None = None
        self._cell_height: int | None = None
        self._braille = False
        self._last_error = ""
        self._last_payload: bytes | None = None

    @property
    def settings(self) -> DotPadSettings:
        return self._settings

    @property
    def status(self) -> TactileDeviceStatus:
        connected = self._handle is not None
        geometry = None
        if connected and self._cell_width is not None and self._cell_height is not None:
            geometry = TactileGeometry(self._cell_width * 2, self._cell_height * 4)
        try:
            count = self._sdk.connected_count()
        except Exception:
            count = 1 if connected else 0
        state = "error" if self._last_error else ("connected" if connected else "disconnected")
        return TactileDeviceStatus(connected, state, self._last_error or state, count, geometry)

    @property
    def capabilities(self) -> TactileCapabilities:
        if self._handle is None or self._cell_width is None or self._cell_height is None:
            raise TactileAdapterError("device is not connected", code=TactileAdapterErrorCode.NOT_CONNECTED)
        return TactileCapabilities(
            provider="dotpad",
            connection=self._settings.connection,
            geometry=TactileGeometry(self._cell_width * 2, self._cell_height * 4),
            supports_graphics=True,
            supports_braille=self._braille,
        )

    @property
    def last_payload(self) -> bytes | None:
        return self._last_payload

    def connect(self) -> TactileCapabilities:
        if self._handle is not None:
            return self.capabilities
        self._last_error = ""
        baseline = self._sdk.connected_count()
        try:
            if self._settings.connection == "serial":
                self._sdk.connect_serial(self._settings.serial_port or "")
            else:
                self._sdk.connect_ble(self._settings.ble_name or "")
            deadline = time.monotonic() + self._settings.connect_timeout_seconds
            while time.monotonic() < deadline:
                count = self._sdk.connected_count()
                if count > baseline or count > 0:
                    handle = self._sdk.connected_handle(count - 1)
                    width, height, braille = self._sdk.display_info(handle)
                    if width <= 0 or height <= 0 or width * height > 4096:
                        raise TactileAdapterError("device reported invalid geometry", code=TactileAdapterErrorCode.SDK_FAILURE)
                    self._handle, self._cell_width, self._cell_height, self._braille = handle, width, height, braille
                    return self.capabilities
                time.sleep(0.02)
        except TactileAdapterError:
            self._fail_safe_disconnect()
            raise
        except Exception as exc:
            self._fail_safe_disconnect()
            raise TactileAdapterError("DotPad connection failed", code=TactileAdapterErrorCode.SDK_FAILURE) from exc
        self._fail_safe_disconnect()
        self._last_error = "connection timed out"
        raise TactileAdapterError("DotPad connection timed out", code=TactileAdapterErrorCode.CONNECT_TIMEOUT)

    def render(self, frame: TactilePinFrame) -> None:
        if self._handle is None or self._cell_width is None or self._cell_height is None:
            raise TactileAdapterError("cannot render while disconnected", code=TactileAdapterErrorCode.NOT_CONNECTED)
        payload = encode_dotpad_graphics(frame, cell_width=self._cell_width, cell_height=self._cell_height)
        try:
            ok = self._sdk.display_data(payload, self._handle)
        except Exception as exc:
            self._last_error = "render failed"
            self._clear_after_render_failure()
            raise TactileAdapterError("DotPad render failed", code=TactileAdapterErrorCode.RENDER_FAILED) from exc
        if not ok:
            self._last_error = "render failed"
            self._clear_after_render_failure()
            raise TactileAdapterError("DotPad rejected tactile frame", code=TactileAdapterErrorCode.RENDER_FAILED)
        self._last_payload = payload
        self._last_error = ""

    def clear(self) -> None:
        if self._handle is None:
            return
        try:
            ok = self._sdk.reset_display(self._handle)
        except Exception as exc:
            raise TactileAdapterError("DotPad display reset failed", code=TactileAdapterErrorCode.SDK_FAILURE) from exc
        if not ok:
            raise TactileAdapterError("DotPad display reset failed", code=TactileAdapterErrorCode.SDK_FAILURE)
        self._last_payload = None

    def disconnect(self) -> None:
        handle = self._handle
        if handle is None:
            return
        if self._settings.clear_on_disconnect:
            try:
                self._sdk.reset_display(handle)
            except Exception:
                pass
        try:
            self._sdk.disconnect(handle)
        finally:
            self._handle = None
            self._cell_width = None
            self._cell_height = None
            self._braille = False
            self._last_payload = None

    def close(self) -> None:
        try:
            self.disconnect()
        finally:
            self._sdk.close()

    def _clear_after_render_failure(self) -> None:
        if self._handle is not None:
            try:
                self._sdk.reset_display(self._handle)
            except Exception:
                pass
        self._last_payload = None

    def _fail_safe_disconnect(self) -> None:
        try:
            self._sdk.disconnect(None)
        except Exception:
            pass
        self._handle = None
        self._cell_width = None
        self._cell_height = None
        self._braille = False
        self._last_payload = None

    def __enter__(self) -> "DotPadTactileAdapter":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
