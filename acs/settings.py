from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import tempfile
import secrets
from typing import Any, Mapping


SCHEMA_VERSION = 2

DEFAULTS: dict[str, Any] = {
    "language": "uk",
    "notation": "uk_literal",
    "sounds": True,
    "volume": 80,
    "tick_policy": "my_turn",
    "tick_last_seconds": 0,
    "engine_path": "",
}

_ALLOWED_LANGUAGE = {"uk", "en"}
_ALLOWED_NOTATION = {"san", "uk_literal", "en_literal"}
_ALLOWED_TICK_POLICY = {"off", "my_turn", "both"}


class SettingsError(ValueError):
    pass


class _SettingsSaveLock:
    """Serialize canonical Settings.save() with the Version 2 upgrade lock.

    The lock pathname itself is part of the coordination contract. A save must
    never follow a symlink/reparse point, adopt a replacement inode, or keep
    using an old locked inode after the canonical pathname was substituted.
    """

    def __init__(self, settings_path: Path) -> None:
        self.path = settings_path.parent / ".v2-upgrade.lock"
        self.handle = None

    @staticmethod
    def _reparse(info: os.stat_result) -> bool:
        flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        return bool(getattr(info, "st_file_attributes", 0) & flag)

    @staticmethod
    def _identity(info: os.stat_result) -> tuple[int, int]:
        return int(info.st_dev), int(info.st_ino)

    @classmethod
    def _require_private_regular(cls, info: os.stat_result) -> None:
        if (
            stat.S_ISLNK(info.st_mode)
            or cls._reparse(info)
            or not stat.S_ISREG(info.st_mode)
            or int(getattr(info, "st_nlink", 1)) != 1
        ):
            raise SettingsError(
                "settings upgrade lock must be one private regular file"
            )

    def assert_current(self) -> os.stat_result:
        if self.handle is None:
            raise SettingsError("settings upgrade lock is not held")
        opened = os.fstat(self.handle.fileno())
        self._require_private_regular(opened)
        try:
            current = os.lstat(self.path)
        except OSError as exc:
            raise SettingsError(
                "settings upgrade lock changed while held"
            ) from exc
        try:
            self._require_private_regular(current)
        except SettingsError as exc:
            raise SettingsError(
                "settings upgrade lock changed while held"
            ) from exc
        if self._identity(opened) != self._identity(current):
            raise SettingsError("settings upgrade lock changed while held")
        return opened

    def __enter__(self) -> "_SettingsSaveLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            before = os.lstat(self.path)
        except FileNotFoundError:
            before = None
        except OSError as exc:
            raise SettingsError(
                "settings upgrade lock could not be inspected"
            ) from exc
        if before is not None:
            self._require_private_regular(before)

        flags = os.O_RDWR
        flags |= getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOINHERIT", 0)
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        if before is None:
            flags |= os.O_CREAT | os.O_EXCL
        try:
            descriptor = os.open(self.path, flags, 0o600)
        except OSError as exc:
            raise SettingsError(
                "settings upgrade lock could not be opened safely"
            ) from exc

        try:
            self.handle = os.fdopen(descriptor, "r+b")
            opened = self.assert_current()
            if before is not None and self._identity(before) != self._identity(opened):
                raise SettingsError("settings upgrade lock changed while opening")

            if opened.st_size == 0:
                self.handle.seek(0)
                self.handle.write(b"\0")
                self.handle.flush()
                os.fsync(self.handle.fileno())
                self.assert_current()

            self.handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(
                        self.handle.fileno(),
                        fcntl.LOCK_EX | fcntl.LOCK_NB,
                    )
            except (OSError, BlockingIOError) as exc:
                raise SettingsError(
                    "settings are temporarily locked for Version 2 upgrade"
                ) from exc
            self.assert_current()
            return self
        except BaseException:
            if self.handle is not None:
                self.handle.close()
                self.handle = None
            else:
                os.close(descriptor)
            raise

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.handle is None:
            return
        continuity_error: SettingsError | None = None
        try:
            try:
                self.assert_current()
            except SettingsError as current_error:
                continuity_error = current_error
            self.handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()
            self.handle = None
        if continuity_error is not None and exc_type is None:
            raise continuity_error


def _same_file_identity(first: os.stat_result, second: os.stat_result) -> bool:
    try:
        return os.path.samestat(first, second)
    except (AttributeError, OSError):
        return (first.st_dev, first.st_ino) == (second.st_dev, second.st_ino)


def _require_private_regular(info: os.stat_result, label: str) -> None:
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if (
        stat.S_ISLNK(info.st_mode)
        or bool(getattr(info, "st_file_attributes", 0) & flag)
        or not stat.S_ISREG(info.st_mode)
        or int(getattr(info, "st_nlink", 1)) != 1
    ):
        raise SettingsError(f"{label} must be one private regular file")


def _cleanup_owned_temp(path: Path, expected: os.stat_result) -> None:
    """Delete only the exact private temp inode created by this Settings save."""
    try:
        current = os.lstat(path)
    except OSError:
        return
    try:
        _require_private_regular(current, "settings temporary file")
    except SettingsError:
        return
    if not _same_file_identity(expected, current):
        return

    quarantine = path.parent / (
        f".{path.name}.remove-quarantine-{secrets.token_hex(8)}"
    )
    try:
        os.replace(path, quarantine)
        moved = os.lstat(quarantine)
    except OSError:
        return
    try:
        _require_private_regular(moved, "settings temporary quarantine")
    except SettingsError:
        return
    if not _same_file_identity(expected, moved):
        return
    try:
        quarantine.unlink()
    except OSError:
        return


def _validated_value(key: str, value: Any) -> Any:
    if key not in DEFAULTS:
        raise KeyError(f"unknown setting: {key}")
    if key == "language":
        if value not in _ALLOWED_LANGUAGE:
            raise SettingsError("language must be 'uk' or 'en'")
        return value
    if key == "notation":
        if value not in _ALLOWED_NOTATION:
            raise SettingsError("notation must be san, uk_literal, or en_literal")
        return value
    if key == "sounds":
        if not isinstance(value, bool):
            raise SettingsError("sounds must be boolean")
        return value
    if key == "volume":
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
            raise SettingsError("volume must be an integer in 0..100")
        return value
    if key == "tick_policy":
        if value not in _ALLOWED_TICK_POLICY:
            raise SettingsError("tick_policy must be off, my_turn, or both")
        return value
    if key == "tick_last_seconds":
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 3600:
            raise SettingsError("tick_last_seconds must be an integer in 0..3600")
        return value
    if key == "engine_path":
        if not isinstance(value, str):
            raise SettingsError("engine_path must be a string")
        return value
    return value


def _migrate(raw: Mapping[str, Any]) -> tuple[dict[str, Any], tuple[str, ...]]:
    warnings: list[str] = []
    # A missing schema key is the only legacy-v0 representation.  Do not let
    # JSON booleans, floats or numeric strings masquerade as schema integers:
    # accepting them can reinterpret a corrupted profile as a valid migration.
    if "schema_version" not in raw:
        version = 0
    else:
        version_value = raw["schema_version"]
        if isinstance(version_value, bool) or not isinstance(version_value, int):
            raise SettingsError("invalid settings schema_version")
        version = version_value

    if version > SCHEMA_VERSION:
        raise SettingsError(
            f"settings schema {version} is newer than supported schema {SCHEMA_VERSION}"
        )

    if version < 0:
        raise SettingsError("invalid settings schema_version")

    if version == 0:
        values = {key: raw[key] for key in DEFAULTS if key in raw}
        raw = {"schema_version": 1, "values": values}
        warnings.append("migrated unversioned settings to schema 1")
        version = 1

    if version == 1:
        values = raw.get("values", {})
        if not isinstance(values, Mapping):
            raise SettingsError("settings values must be an object")
        raw = {"schema_version": 2, "values": dict(values)}
        warnings.append("migrated settings schema 1 to schema 2")
        version = 2

    if version != SCHEMA_VERSION:
        raise SettingsError(f"unsupported settings schema {version}")

    values = raw.get("values", {})
    if not isinstance(values, Mapping):
        raise SettingsError("settings values must be an object")
    return dict(values), tuple(warnings)


class Settings:
    """Versioned, recovery-safe application settings.

    Preserves the legacy get/set/data API while adding explicit schema
    migration, validation, atomic writes and import/export support.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.data: dict[str, Any] = dict(DEFAULTS)
        self.warning: str | None = None
        self.load()

    def load(self) -> None:
        self.data = dict(DEFAULTS)
        self.warning = None
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, Mapping):
                raise SettingsError("settings file must contain a JSON object")
            values, migration_warnings = _migrate(raw)
            for key, value in values.items():
                if key not in DEFAULTS:
                    continue
                self.data[key] = _validated_value(key, value)
            if migration_warnings:
                self.warning = "; ".join(migration_warnings)
        except Exception as exc:
            self.data = dict(DEFAULTS)
            self.warning = f"settings recovery: {exc}"

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        validated = _validated_value(key, value)
        self.data[key] = validated
        self.save()

    def reset(self, key: str | None = None) -> None:
        if key is None:
            self.data = dict(DEFAULTS)
        else:
            if key not in DEFAULTS:
                raise KeyError(f"unknown setting: {key}")
            self.data[key] = DEFAULTS[key]
        self.save()

    def to_profile(self) -> dict[str, Any]:
        values = {key: self.data[key] for key in DEFAULTS}
        return {"schema_version": SCHEMA_VERSION, "values": values}

    def export_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_profile(), ensure_ascii=False, indent=indent, sort_keys=True)

    def import_json(self, text: str, *, persist: bool = True) -> tuple[str, ...]:
        raw = json.loads(text)
        if not isinstance(raw, Mapping):
            raise SettingsError("settings profile must be a JSON object")
        values, warnings = _migrate(raw)
        candidate = dict(DEFAULTS)
        for key, value in values.items():
            if key in DEFAULTS:
                candidate[key] = _validated_value(key, value)
        self.data = candidate
        self.warning = "; ".join(warnings) if warnings else None
        if persist:
            self.save()
        return warnings

    def save(self) -> None:
        with _SettingsSaveLock(self.path) as upgrade_lock:
            upgrade_lock.assert_current()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = (self.export_json() + "\n").encode("utf-8")
            fd, raw = tempfile.mkstemp(
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                dir=str(self.path.parent),
            )
            tmp: Path | None = Path(raw)
            prepared: os.stat_result | None = None
            try:
                created = os.fstat(fd)
                _require_private_regular(created, "settings temporary file")
                prepared = created
                stream = os.fdopen(fd, "wb")
                fd = -1
                with stream as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                    prepared = os.fstat(handle.fileno())
                    _require_private_regular(
                        prepared,
                        "settings temporary file",
                    )
                    if not _same_file_identity(created, prepared):
                        raise SettingsError(
                            "settings temporary file changed while being prepared"
                        )

                upgrade_lock.assert_current()
                assert tmp is not None
                current = os.lstat(tmp)
                _require_private_regular(current, "settings temporary file")
                if prepared is None or not _same_file_identity(prepared, current):
                    raise SettingsError(
                        "settings temporary file changed before publication"
                    )

                os.replace(tmp, self.path)
                tmp = None
                published = os.lstat(self.path)
                _require_private_regular(
                    published,
                    "settings publication",
                )
                if not _same_file_identity(prepared, published):
                    raise SettingsError(
                        "settings publication changed before confirmation"
                    )
                upgrade_lock.assert_current()

                # Persist the directory entry where supported. Windows may not
                # allow opening a directory descriptor through the CRT.
                directory_fd = -1
                try:
                    directory_fd = os.open(
                        self.path.parent,
                        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
                    )
                    try:
                        os.fsync(directory_fd)
                    except OSError:
                        if os.name != "nt":
                            raise
                except OSError:
                    if os.name != "nt":
                        raise
                finally:
                    if directory_fd >= 0:
                        os.close(directory_fd)

                confirmed = os.lstat(self.path)
                _require_private_regular(
                    confirmed,
                    "settings publication",
                )
                if not _same_file_identity(prepared, confirmed):
                    raise SettingsError(
                        "settings publication changed before durability confirmation"
                    )
                upgrade_lock.assert_current()
            finally:
                if fd >= 0:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                if tmp is not None and prepared is not None:
                    _cleanup_owned_temp(tmp, prepared)
