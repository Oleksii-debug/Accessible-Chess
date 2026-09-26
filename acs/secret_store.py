from __future__ import annotations

"""Provider-neutral secret storage with a Windows current-user DPAPI adapter."""

from ctypes import POINTER, Structure, byref, c_byte, c_char_p, c_void_p, cast, create_string_buffer, memmove, sizeof, string_at, windll
from ctypes.wintypes import BOOL, DWORD, LPWSTR
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from typing import Protocol, runtime_checkable


_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_CRYPTPROTECT_UI_FORBIDDEN = 0x1
_ENTROPY = b"Accessible Chess SecretStore v1"


class SecretStoreError(RuntimeError):
    """Raised when secret persistence cannot be completed safely."""


@runtime_checkable
class SecretStore(Protocol):
    def write(self, name: str, value: bytes) -> None: ...
    def read(self, name: str) -> bytes | None: ...
    def delete(self, name: str) -> bool: ...


def _name(value: str) -> str:
    text = str(value)
    if not _NAME_RE.fullmatch(text):
        raise SecretStoreError("secret name must be a safe stable identifier")
    return text


def _is_reparse(info: os.stat_result) -> bool:
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(info, "st_file_attributes", 0) & flag)


def _reject_link(path: Path, *, label: str) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise SecretStoreError(f"{label} cannot be inspected: {type(exc).__name__}") from exc
    if stat.S_ISLNK(info.st_mode) or _is_reparse(info):
        raise SecretStoreError(f"{label} must not be a symlink or reparse point")


if sys.platform == "win32":
    class _DATA_BLOB(Structure):
        _fields_ = [("cbData", DWORD), ("pbData", POINTER(c_byte))]


    def _blob(data: bytes):
        if not data:
            buffer = create_string_buffer(b"\x00", 1)
            return _DATA_BLOB(0, cast(buffer, POINTER(c_byte))), buffer
        buffer = create_string_buffer(data, len(data))
        return _DATA_BLOB(len(data), cast(buffer, POINTER(c_byte))), buffer


    def _dpapi_protect(data: bytes) -> bytes:
        source, source_buffer = _blob(data)
        entropy, entropy_buffer = _blob(_ENTROPY)
        output = _DATA_BLOB()
        crypt32 = windll.crypt32
        kernel32 = windll.kernel32
        crypt32.CryptProtectData.argtypes = [
            POINTER(_DATA_BLOB), LPWSTR, POINTER(_DATA_BLOB), c_void_p, c_void_p,
            DWORD, POINTER(_DATA_BLOB),
        ]
        crypt32.CryptProtectData.restype = BOOL
        ok = crypt32.CryptProtectData(
            byref(source), "Accessible Chess protected secret", byref(entropy),
            None, None, _CRYPTPROTECT_UI_FORBIDDEN, byref(output),
        )
        _ = source_buffer, entropy_buffer
        if not ok:
            raise SecretStoreError("Windows DPAPI protection failed")
        try:
            return string_at(output.pbData, output.cbData)
        finally:
            if output.pbData:
                kernel32.LocalFree(output.pbData)


    def _dpapi_unprotect(data: bytes) -> bytes:
        source, source_buffer = _blob(data)
        entropy, entropy_buffer = _blob(_ENTROPY)
        output = _DATA_BLOB()
        description = LPWSTR()
        crypt32 = windll.crypt32
        kernel32 = windll.kernel32
        crypt32.CryptUnprotectData.argtypes = [
            POINTER(_DATA_BLOB), POINTER(LPWSTR), POINTER(_DATA_BLOB), c_void_p,
            c_void_p, DWORD, POINTER(_DATA_BLOB),
        ]
        crypt32.CryptUnprotectData.restype = BOOL
        ok = crypt32.CryptUnprotectData(
            byref(source), byref(description), byref(entropy), None, None,
            _CRYPTPROTECT_UI_FORBIDDEN, byref(output),
        )
        _ = source_buffer, entropy_buffer
        if not ok:
            raise SecretStoreError("Windows DPAPI unprotection failed")
        try:
            return string_at(output.pbData, output.cbData)
        finally:
            if output.pbData:
                kernel32.LocalFree(output.pbData)
            if description:
                kernel32.LocalFree(description)
else:
    def _dpapi_protect(data: bytes) -> bytes:
        raise SecretStoreError("Windows DPAPI is unavailable on this platform")


    def _dpapi_unprotect(data: bytes) -> bytes:
        raise SecretStoreError("Windows DPAPI is unavailable on this platform")


@dataclass(frozen=True)
class WindowsDpapiSecretStore:
    root: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", Path(self.root))

    @classmethod
    def for_current_user(cls, *, app_name: str = "AccessibleChess") -> "WindowsDpapiSecretStore":
        if sys.platform != "win32":
            raise SecretStoreError("Windows DPAPI is unavailable on this platform")
        local = os.environ.get("LOCALAPPDATA")
        if not local:
            raise SecretStoreError("LOCALAPPDATA is unavailable")
        if not _NAME_RE.fullmatch(app_name):
            raise SecretStoreError("app_name must be a safe stable identifier")
        return cls(Path(local) / app_name / "secure")

    def _path(self, name: str) -> Path:
        token = _name(name)
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        return self.root / f"{digest}.dpapi"

    def _prepare_root(self) -> None:
        _reject_link(self.root, label="secret store root")
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise SecretStoreError(f"secret store root cannot be created: {type(exc).__name__}") from exc
        _reject_link(self.root, label="secret store root")
        try:
            if not self.root.is_dir():
                raise SecretStoreError("secret store root must be a directory")
        except OSError as exc:
            raise SecretStoreError(f"secret store root cannot be inspected: {type(exc).__name__}") from exc

    def write(self, name: str, value: bytes) -> None:
        if sys.platform != "win32":
            raise SecretStoreError("Windows DPAPI is unavailable on this platform")
        if not isinstance(value, bytes):
            raise SecretStoreError("secret value must be bytes")
        self._prepare_root()
        target = self._path(name)
        _reject_link(target, label="secret file")
        protected = _dpapi_protect(value)
        temp_path: Path | None = None
        try:
            fd, raw_temp = tempfile.mkstemp(prefix=".secret-", suffix=".tmp", dir=self.root)
            temp_path = Path(raw_temp)
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(protected)
                    handle.flush()
                    os.fsync(handle.fileno())
                _reject_link(target, label="secret file")
                os.replace(temp_path, target)
                temp_path = None
            except Exception:
                try:
                    os.close(fd)
                except OSError:
                    pass
                raise
        except SecretStoreError:
            raise
        except OSError as exc:
            raise SecretStoreError(f"secret ciphertext cannot be persisted: {type(exc).__name__}") from exc
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def read(self, name: str) -> bytes | None:
        if sys.platform != "win32":
            raise SecretStoreError("Windows DPAPI is unavailable on this platform")
        self._prepare_root()
        target = self._path(name)
        _reject_link(target, label="secret file")
        try:
            data = target.read_bytes()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise SecretStoreError(f"secret ciphertext cannot be read: {type(exc).__name__}") from exc
        if not data:
            raise SecretStoreError("secret ciphertext is empty")
        return _dpapi_unprotect(data)

    def delete(self, name: str) -> bool:
        if sys.platform != "win32":
            raise SecretStoreError("Windows DPAPI is unavailable on this platform")
        self._prepare_root()
        target = self._path(name)
        _reject_link(target, label="secret file")
        try:
            target.unlink()
            return True
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise SecretStoreError(f"secret ciphertext cannot be deleted: {type(exc).__name__}") from exc
