from __future__ import annotations

"""Device-neutral DTOs and DotPad graphics encoding for Section 9."""

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable


class TactileAdapterErrorCode(str, Enum):
    SDK_UNAVAILABLE = "sdk_unavailable"
    UNSUPPORTED_PLATFORM = "unsupported_platform"
    INVALID_SETTINGS = "invalid_settings"
    NOT_CONNECTED = "not_connected"
    CONNECT_TIMEOUT = "connect_timeout"
    DEVICE_UNAVAILABLE = "device_unavailable"
    SDK_FAILURE = "sdk_failure"
    INVALID_FRAME = "invalid_frame"
    GEOMETRY_MISMATCH = "geometry_mismatch"
    RENDER_FAILED = "render_failed"


class TactileAdapterError(RuntimeError):
    def __init__(self, message: str, *, code: TactileAdapterErrorCode) -> None:
        super().__init__(message)
        self.code = TactileAdapterErrorCode(code)


@dataclass(frozen=True, slots=True)
class TactileGeometry:
    width: int
    height: int

    def __post_init__(self) -> None:
        if type(self.width) is not int or type(self.height) is not int:
            raise TactileAdapterError("tactile geometry must use integers", code=TactileAdapterErrorCode.INVALID_SETTINGS)
        if self.width <= 0 or self.height <= 0 or self.width > 4096 or self.height > 4096:
            raise TactileAdapterError("tactile geometry is out of bounds", code=TactileAdapterErrorCode.INVALID_SETTINGS)


@dataclass(frozen=True, slots=True)
class TactileCapabilities:
    provider: str
    connection: str
    geometry: TactileGeometry
    supports_graphics: bool = True
    supports_braille: bool = True


@dataclass(frozen=True, slots=True)
class TactileDeviceStatus:
    connected: bool
    state: str
    detail: str
    device_count: int
    geometry: TactileGeometry | None = None


@dataclass(frozen=True, slots=True)
class DotPadSettings:
    connection: str = "serial"
    serial_port: str | None = None
    ble_name: str | None = None
    sdk_path: str | None = None
    connect_timeout_seconds: float = 3.0
    clear_on_disconnect: bool = True

    def __post_init__(self) -> None:
        if type(self.connection) is not str or self.connection not in {"serial", "ble"}:
            raise TactileAdapterError("connection must be serial or ble", code=TactileAdapterErrorCode.INVALID_SETTINGS)
        if self.connection == "serial":
            if type(self.serial_port) is not str or not self.serial_port.strip():
                raise TactileAdapterError("serial connection requires a COM port", code=TactileAdapterErrorCode.INVALID_SETTINGS)
            object.__setattr__(self, "serial_port", self.serial_port.strip())
        else:
            if type(self.ble_name) is not str or not self.ble_name.strip():
                raise TactileAdapterError("BLE connection requires a device name", code=TactileAdapterErrorCode.INVALID_SETTINGS)
            object.__setattr__(self, "ble_name", self.ble_name.strip())
        if self.sdk_path is not None:
            if type(self.sdk_path) is not str or not self.sdk_path.strip():
                raise TactileAdapterError("SDK path must be non-empty text or None", code=TactileAdapterErrorCode.INVALID_SETTINGS)
            object.__setattr__(self, "sdk_path", self.sdk_path.strip())
        if type(self.connect_timeout_seconds) not in {int, float} or isinstance(self.connect_timeout_seconds, bool):
            raise TactileAdapterError("connect timeout must be numeric", code=TactileAdapterErrorCode.INVALID_SETTINGS)
        timeout = float(self.connect_timeout_seconds)
        if not 0.05 <= timeout <= 60.0:
            raise TactileAdapterError("connect timeout must be 0.05..60 seconds", code=TactileAdapterErrorCode.INVALID_SETTINGS)
        object.__setattr__(self, "connect_timeout_seconds", timeout)
        if type(self.clear_on_disconnect) is not bool:
            raise TactileAdapterError("clear_on_disconnect must be boolean", code=TactileAdapterErrorCode.INVALID_SETTINGS)


@dataclass(frozen=True, slots=True)
class TactilePinFrame:
    """Immutable pin-only handoff from the Section-8 scene/render layer."""

    width: int
    height: int
    pins: tuple[bool, ...]

    def __post_init__(self) -> None:
        geometry = TactileGeometry(self.width, self.height)
        if type(self.pins) is not tuple or len(self.pins) != geometry.width * geometry.height:
            raise TactileAdapterError("pin frame size does not match geometry", code=TactileAdapterErrorCode.INVALID_FRAME)
        if any(type(value) is not bool for value in self.pins):
            raise TactileAdapterError("pin frame contains a non-boolean value", code=TactileAdapterErrorCode.INVALID_FRAME)


@runtime_checkable
class DotPadSdkApi(Protocol):
    def connect_serial(self, port_name: str) -> None: ...
    def connect_ble(self, device_name: str) -> None: ...
    def connected_count(self) -> int: ...
    def connected_handle(self, index: int) -> int: ...
    def display_info(self, handle: int) -> tuple[int, int, bool]: ...
    def display_data(self, payload: bytes, handle: int) -> bool: ...
    def reset_display(self, handle: int) -> bool: ...
    def disconnect(self, handle: int | None) -> bool: ...
    def close(self) -> None: ...


_DOT_CELL_PIN_TO_BIT = (
    (0, 0, 0), (0, 1, 1), (0, 2, 2),
    (1, 0, 3), (1, 1, 4), (1, 2, 5),
    (0, 3, 6), (1, 3, 7),
)


def encode_dotpad_graphics(frame: TactilePinFrame, *, cell_width: int, cell_height: int) -> bytes:
    """Encode a 2x4-pin-per-cell scene to DotPad graphics-cell bytes."""
    if type(frame) is not TactilePinFrame:
        raise TactileAdapterError("render input must be a TactilePinFrame", code=TactileAdapterErrorCode.INVALID_FRAME)
    if type(cell_width) is not int or type(cell_height) is not int or cell_width <= 0 or cell_height <= 0:
        raise TactileAdapterError("device cell geometry is invalid", code=TactileAdapterErrorCode.GEOMETRY_MISMATCH)
    if frame.width != cell_width * 2 or frame.height != cell_height * 4:
        raise TactileAdapterError("pin frame geometry does not match connected DotPad", code=TactileAdapterErrorCode.GEOMETRY_MISMATCH)
    payload = bytearray(cell_width * cell_height)
    for cy in range(cell_height):
        for cx in range(cell_width):
            cell = 0
            ox, oy = cx * 2, cy * 4
            for dx, dy, bit in _DOT_CELL_PIN_TO_BIT:
                if frame.pins[(oy + dy) * frame.width + (ox + dx)]:
                    cell |= 1 << bit
            payload[cy * cell_width + cx] = cell
    return bytes(payload)
