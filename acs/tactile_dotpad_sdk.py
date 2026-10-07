from __future__ import annotations

"""Official DotPad Windows SDK binding and deterministic SDK simulator."""

import ctypes
import os
from pathlib import Path
import sys

from .tactile_dotpad_contract import TactileAdapterError, TactileAdapterErrorCode


class CtypesDotPadSdkApi:
    """Dynamic binding to the documented DotPad SDK 3.x C API."""

    DEFAULT_DLL_NAME = "DotPadSDK-3.0.0.dll"

    def __init__(self, sdk_path: str | os.PathLike[str] | None = None) -> None:
        if sys.platform != "win32":
            raise TactileAdapterError("DotPad SDK requires Windows", code=TactileAdapterErrorCode.UNSUPPORTED_PLATFORM)
        path = self._resolve_sdk_path(sdk_path)
        self._dll_dir = None
        if path.parent != Path(".") and hasattr(os, "add_dll_directory"):
            try:
                self._dll_dir = os.add_dll_directory(str(path.parent.resolve()))
            except OSError:
                self._dll_dir = None
        try:
            self._dll = ctypes.WinDLL(str(path))
        except (OSError, AttributeError) as exc:
            raise TactileAdapterError("DotPad SDK could not be loaded", code=TactileAdapterErrorCode.SDK_UNAVAILABLE) from exc
        self._closed = False
        try:
            self._bind()
        except (AttributeError, TypeError, ValueError) as exc:
            self.close()
            raise TactileAdapterError("DotPad SDK is missing a required API", code=TactileAdapterErrorCode.SDK_UNAVAILABLE) from exc

    @classmethod
    def _resolve_sdk_path(cls, sdk_path: str | os.PathLike[str] | None) -> Path:
        if sdk_path is not None:
            candidate = Path(sdk_path)
            if candidate.is_dir():
                matches = sorted(candidate.glob("DotPadSDK*.dll"), reverse=True)
                return matches[0] if matches else candidate / cls.DEFAULT_DLL_NAME
            return candidate
        env = os.environ.get("ACCESSIBLE_CHESS_DOTPAD_SDK")
        if env:
            return cls._resolve_sdk_path(env)
        cwd = Path.cwd()
        preferred = [cwd / "DotPadSDK.dll", cwd / cls.DEFAULT_DLL_NAME]
        preferred.extend(sorted(cwd.glob("DotPadSDK-3.*.dll"), reverse=True))
        for candidate in preferred:
            if candidate.exists():
                return candidate
        return Path("DotPadSDK.dll")

    def _bind(self) -> None:
        self._connect_serial = self._dll.DOT_PAD_CONNECT_SERIAL
        self._connect_serial.argtypes, self._connect_serial.restype = [ctypes.c_wchar_p], None
        self._connect_ble = self._dll.DOT_PAD_CONNECT_BLE
        self._connect_ble.argtypes, self._connect_ble.restype = [ctypes.c_wchar_p], None
        self._connected_count = self._dll.DOT_PAD_GET_CONNECTED_DEVICE_COUNT
        self._connected_count.argtypes, self._connected_count.restype = [], ctypes.c_int
        self._connected_handle = self._dll.DOT_PAD_GET_CONNECTED_DEVICE_HANDLE
        self._connected_handle.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)]
        self._connected_handle.restype = ctypes.c_bool
        self._display_info = self._dll.DOT_PAD_GET_DISPLAY_INFO
        self._display_info.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)]
        self._display_info.restype = ctypes.c_bool
        self._display_data = self._dll.DOT_PAD_DISPLAY_DATA
        self._display_data.argtypes = [ctypes.POINTER(ctypes.c_uint8), ctypes.c_int, ctypes.c_void_p]
        self._display_data.restype = ctypes.c_bool
        self._reset_display = self._dll.DOT_PAD_RESET_DISPLAY
        self._reset_display.argtypes, self._reset_display.restype = [ctypes.c_void_p], ctypes.c_bool
        self._disconnect = self._dll.DOT_PAD_DISCONNECT
        self._disconnect.argtypes, self._disconnect.restype = [ctypes.c_void_p], ctypes.c_bool

    def _ensure_open(self) -> None:
        if self._closed:
            raise TactileAdapterError("DotPad SDK is closed", code=TactileAdapterErrorCode.SDK_FAILURE)

    def connect_serial(self, port_name: str) -> None:
        self._ensure_open(); self._connect_serial(port_name)

    def connect_ble(self, device_name: str) -> None:
        self._ensure_open(); self._connect_ble(device_name)

    def connected_count(self) -> int:
        self._ensure_open(); return max(0, int(self._connected_count()))

    def connected_handle(self, index: int) -> int:
        self._ensure_open(); handle = ctypes.c_void_p()
        if not self._connected_handle(index, ctypes.byref(handle)) or not handle.value:
            raise TactileAdapterError("connected device handle unavailable", code=TactileAdapterErrorCode.DEVICE_UNAVAILABLE)
        return int(handle.value)

    def display_info(self, handle: int) -> tuple[int, int, bool]:
        self._ensure_open(); width, height, braille = ctypes.c_int(), ctypes.c_int(), ctypes.c_int()
        ok = self._display_info(ctypes.c_void_p(handle), ctypes.byref(width), ctypes.byref(height), ctypes.byref(braille))
        if not ok or width.value <= 0 or height.value <= 0:
            raise TactileAdapterError("display geometry unavailable", code=TactileAdapterErrorCode.SDK_FAILURE)
        return int(width.value), int(height.value), bool(braille.value)

    def display_data(self, payload: bytes, handle: int) -> bool:
        self._ensure_open()
        if type(payload) is not bytes or not payload:
            return False
        data = (ctypes.c_uint8 * len(payload)).from_buffer_copy(payload)
        return bool(self._display_data(data, len(payload), ctypes.c_void_p(handle)))

    def reset_display(self, handle: int) -> bool:
        self._ensure_open(); return bool(self._reset_display(ctypes.c_void_p(handle)))

    def disconnect(self, handle: int | None) -> bool:
        self._ensure_open(); return bool(self._disconnect(ctypes.c_void_p(handle) if handle is not None else None))

    def close(self) -> None:
        if getattr(self, "_closed", True):
            return
        try:
            self._disconnect(None)
        except Exception:
            pass
        self._closed = True
        self._dll = None
        if self._dll_dir is not None:
            try:
                self._dll_dir.close()
            except Exception:
                pass
            self._dll_dir = None


class DotPadSdkSimulator:
    """Deterministic SDK-level simulator for adapter parity tests."""

    def __init__(self, *, cell_width: int = 30, cell_height: int = 10, braille: bool = True) -> None:
        if type(cell_width) is not int or type(cell_height) is not int or cell_width <= 0 or cell_height <= 0:
            raise ValueError("simulator geometry must be positive")
        self.cell_width, self.cell_height, self.braille = cell_width, cell_height, bool(braille)
        self.connected = False
        self.closed = False
        self.last_payload: bytes | None = None
        self.reset_count = 0
        self.fail_next_render = False

    def _open(self) -> None:
        if self.closed:
            raise RuntimeError("simulator is closed")

    def connect_serial(self, port_name: str) -> None:
        self._open(); self.connected = bool(port_name)

    def connect_ble(self, device_name: str) -> None:
        self._open(); self.connected = bool(device_name)

    def connected_count(self) -> int:
        self._open(); return 1 if self.connected else 0

    def connected_handle(self, index: int) -> int:
        self._open()
        if not self.connected or index != 0:
            raise RuntimeError("device unavailable")
        return 1

    def display_info(self, handle: int) -> tuple[int, int, bool]:
        self._open()
        if not self.connected or handle != 1:
            raise RuntimeError("device unavailable")
        return self.cell_width, self.cell_height, self.braille

    def display_data(self, payload: bytes, handle: int) -> bool:
        self._open()
        if not self.connected or handle != 1:
            return False
        if self.fail_next_render:
            self.fail_next_render = False
            return False
        if type(payload) is not bytes or len(payload) != self.cell_width * self.cell_height:
            return False
        self.last_payload = payload
        return True

    def reset_display(self, handle: int) -> bool:
        self._open()
        if not self.connected or handle != 1:
            return False
        self.last_payload = None
        self.reset_count += 1
        return True

    def disconnect(self, handle: int | None) -> bool:
        self._open(); self.connected = False; self.last_payload = None; return True

    def close(self) -> None:
        self.connected = False; self.last_payload = None; self.closed = True
