from __future__ import annotations

"""Provider-neutral secret storage with a Windows current-user DPAPI adapter."""

import ctypes
from ctypes import POINTER, Structure, byref, c_byte, c_void_p, cast, create_string_buffer, string_at
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
_MAX_SECRET_BYTES = 64 * 1024
_MAX_CIPHERTEXT_BYTES = 1024 * 1024


class SecretStoreError(RuntimeError):
    """Raised when secret persistence cannot be completed safely."""


@runtime_checkable
class SecretStore(Protocol):
    def write(self, name: str, value: bytes) -> None: ...
    def read(self, name: str) -> bytes | None: ...
    def delete(self, name: str) -> bool: ...


def _name(value: str) -> str:
    if type(value) is not str or not _NAME_RE.fullmatch(value):
        raise SecretStoreError("secret name must be a safe stable identifier")
    return value


def _slot_entropy(name: str) -> bytes:
    token = _name(name)
    return hashlib.sha256(_ENTROPY + b"\x00slot\x00" + token.encode("utf-8")).digest()


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


def _reject_link_ancestry(path: Path) -> None:
    """Reject any existing symlink/reparse component leading to the store root."""

    candidate = Path(path)
    chain = list(reversed((candidate, *candidate.parents)))
    for component in chain:
        _reject_link(component, label="secret store ancestry")


if sys.platform == "win32":
    class _DATA_BLOB(Structure):
        _fields_ = [("cbData", DWORD), ("pbData", POINTER(c_byte))]


    def _blob(data: bytes):
        if not data:
            buffer = create_string_buffer(b"\x00", 1)
            return _DATA_BLOB(0, cast(buffer, POINTER(c_byte))), buffer
        buffer = create_string_buffer(data, len(data))
        return _DATA_BLOB(len(data), cast(buffer, POINTER(c_byte))), buffer


    def _dpapi_protect(data: bytes, *, entropy: bytes) -> bytes:
        source, source_buffer = _blob(data)
        entropy_blob, entropy_buffer = _blob(entropy)
        output = _DATA_BLOB()
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        crypt32.CryptProtectData.argtypes = [
            POINTER(_DATA_BLOB), LPWSTR, POINTER(_DATA_BLOB), c_void_p, c_void_p,
            DWORD, POINTER(_DATA_BLOB),
        ]
        crypt32.CryptProtectData.restype = BOOL
        ok = crypt32.CryptProtectData(
            byref(source), "Accessible Chess protected secret", byref(entropy_blob),
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


    def _dpapi_unprotect(data: bytes, *, entropy: bytes) -> bytes:
        source, source_buffer = _blob(data)
        entropy_blob, entropy_buffer = _blob(entropy)
        output = _DATA_BLOB()
        description = LPWSTR()
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        crypt32.CryptUnprotectData.argtypes = [
            POINTER(_DATA_BLOB), POINTER(LPWSTR), POINTER(_DATA_BLOB), c_void_p,
            c_void_p, DWORD, POINTER(_DATA_BLOB),
        ]
        crypt32.CryptUnprotectData.restype = BOOL
        ok = crypt32.CryptUnprotectData(
            byref(source), byref(description), byref(entropy_blob), None, None,
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
    def _dpapi_protect(data: bytes, *, entropy: bytes) -> bytes:
        raise SecretStoreError("Windows DPAPI is unavailable on this platform")


    def _dpapi_unprotect(data: bytes, *, entropy: bytes) -> bytes:
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
        if type(app_name) is not str or not _NAME_RE.fullmatch(app_name):
            raise SecretStoreError("app_name must be a safe stable identifier")
        return cls(Path(local) / app_name / "secure")

    def _path(self, name: str) -> Path:
        token = _name(name)
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        return self.root / f"{digest}.dpapi"

    def _prepare_root(self) -> None:
        _reject_link_ancestry(self.root)
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise SecretStoreError(f"secret store root cannot be created: {type(exc).__name__}") from exc
        _reject_link_ancestry(self.root)
        try:
            if not self.root.is_dir():
                raise SecretStoreError("secret store root must be a directory")
        except OSError as exc:
            raise SecretStoreError(f"secret store root cannot be inspected: {type(exc).__name__}") from exc

    def write(self, name: str, value: bytes) -> None:
        if sys.platform != "win32":
            raise SecretStoreError("Windows DPAPI is unavailable on this platform")
        if type(value) is not bytes:
            raise SecretStoreError("secret value must be bytes")
        if not value:
            raise SecretStoreError("secret value must not be empty")
        if len(value) > _MAX_SECRET_BYTES:
            raise SecretStoreError("secret value exceeds size limit")
        self._prepare_root()
        target = self._path(name)
        _reject_link(target, label="secret file")
        protected = _dpapi_protect(value, entropy=_slot_entropy(name))
        if not protected or len(protected) > _MAX_CIPHERTEXT_BYTES:
            raise SecretStoreError("Windows DPAPI returned invalid ciphertext")
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
            info = target.stat()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise SecretStoreError(f"secret ciphertext cannot be inspected: {type(exc).__name__}") from exc
        if info.st_size <= 0:
            raise SecretStoreError("secret ciphertext is empty")
        if info.st_size > _MAX_CIPHERTEXT_BYTES:
            raise SecretStoreError("secret ciphertext exceeds size limit")
        try:
            data = target.read_bytes()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise SecretStoreError(f"secret ciphertext cannot be read: {type(exc).__name__}") from exc
        if not data:
            raise SecretStoreError("secret ciphertext is empty")
        if len(data) > _MAX_CIPHERTEXT_BYTES:
            raise SecretStoreError("secret ciphertext exceeds size limit")
        plaintext = _dpapi_unprotect(data, entropy=_slot_entropy(name))
        if not plaintext:
            raise SecretStoreError("unprotected secret is empty")
        if len(plaintext) > _MAX_SECRET_BYTES:
            raise SecretStoreError("unprotected secret exceeds size limit")
        return plaintext

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
