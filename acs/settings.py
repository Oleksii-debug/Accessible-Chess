from __future__ import annotations

import errno
import json
import os
from pathlib import Path
import secrets
import stat
import tempfile
from typing import Any, Mapping


SCHEMA_VERSION = 2

DEFAULTS: dict[str, Any] = {
    "language": "uk",
    "notation": "uk_literal",
    "sounds": True,
    "newgame_animation": True,
    "volume": 80,
    "tick_policy": "my_turn",
    "tick_last_seconds": 0,
    "low_time_policy": "my_turn",
    "low_time_seconds": 30,
    "engine_path": "",
    "sound_move_variant": "1",
    "sound_capture_variant": "1",
    "sound_check_variant": "1",
    "sound_castle_variant": "1",
    "sound_promotion_variant": "1",
    "sound_illegal_variant": "1",
    "sound_start_variant": "1",
    "sound_end_variant": "1",
    "sound_mate_variant": "1",
    "sound_draw_variant": "1",
    "sound_tick_variant": "1",
    "sound_low_time_variant": "1",
}

_ALLOWED_LANGUAGE = {"uk", "en"}
_ALLOWED_NOTATION = {"san", "uk_literal", "en_literal"}
_ALLOWED_TICK_POLICY = {"off", "my_turn", "both"}
_SOUND_VARIANT_KEYS = frozenset(
    {
        "sound_move_variant",
        "sound_capture_variant",
        "sound_check_variant",
        "sound_castle_variant",
        "sound_promotion_variant",
        "sound_illegal_variant",
        "sound_start_variant",
        "sound_end_variant",
        "sound_mate_variant",
        "sound_draw_variant",
        "sound_tick_variant",
        "sound_low_time_variant",
    }
)


class SettingsError(ValueError):
    pass


def _reparse(info: os.stat_result) -> bool:
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(info, "st_file_attributes", 0) & flag)


def _identity(info: os.stat_result) -> tuple[int, int]:
    return int(info.st_dev), int(info.st_ino)


def _same_file_identity(first: os.stat_result, second: os.stat_result) -> bool:
    try:
        return os.path.samestat(first, second)
    except (AttributeError, OSError):
        return _identity(first) == _identity(second)


def _require_private_regular(info: os.stat_result, label: str) -> None:
    if (
        stat.S_ISLNK(info.st_mode)
        or _reparse(info)
        or not stat.S_ISREG(info.st_mode)
        or int(getattr(info, "st_nlink", 1)) != 1
    ):
        raise SettingsError(f"{label} must be one private regular file")


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        if os.name == "nt" or exc.errno in {
            errno.EACCES,
            errno.EINVAL,
            errno.ENOTSUP,
        }:
            return
        raise SettingsError("settings directory could not be synchronized") from exc
    try:
        try:
            os.fsync(descriptor)
        except OSError as exc:
            if os.name != "nt" and exc.errno not in {errno.EINVAL, errno.ENOTSUP}:
                raise SettingsError(
                    "settings directory could not be synchronized"
                ) from exc
    finally:
        os.close(descriptor)


def _remove_exact_private_file(
    path: Path,
    *,
    expected_identity: tuple[int, int],
    label: str,
) -> None:
    """Delete only the exact private inode created by this Settings writer."""
    try:
        before = path.lstat()
    except OSError as exc:
        raise SettingsError(f"{label} could not be inspected safely") from exc
    _require_private_regular(before, label)
    if _identity(before) != expected_identity:
        raise SettingsError(f"{label} changed unexpectedly")

    quarantine: Path | None = None
    for _ in range(8):
        candidate = path.parent / (
            f".{path.name}.remove-quarantine-{secrets.token_hex(8)}"
        )
        if candidate.exists() or candidate.is_symlink():
            continue
        quarantine = candidate
        break
    if quarantine is None:
        raise SettingsError(f"{label} cleanup quarantine could not be allocated")

    try:
        os.replace(path, quarantine)
    except OSError as exc:
        raise SettingsError(f"{label} could not be quarantined safely") from exc

    moved = quarantine.lstat()
    _require_private_regular(moved, f"{label} quarantine")
    if _identity(moved) != expected_identity:
        raise SettingsError(f"{label} changed during cleanup")
    try:
        quarantine.unlink()
    except OSError as exc:
        raise SettingsError(f"{label} could not be removed safely") from exc
    _fsync_directory(path.parent)


class _SettingsSaveLock:
    """Serialize canonical Settings.save() with the Version 2 upgrade lock.

    Both the upgrader and the canonical Settings writer must coordinate on the
    exact same lock inode.  Do not adopt symlink/reparse/hard-linked lock files,
    and re-authenticate pathname-to-handle identity after acquisition and around
    publication so a replaced lock pathname cannot silently split coordination.
    """

    def __init__(self, settings_path: Path) -> None:
        self.path = settings_path.parent / ".v2-upgrade.lock"
        self.handle = None
        self.identity: tuple[int, int] | None = None

    def _require_current_handle(self) -> os.stat_result:
        if self.handle is None:
            raise SettingsError("settings upgrade lock is not open")
        opened = os.fstat(self.handle.fileno())
        _require_private_regular(opened, "settings upgrade lock")
        try:
            current = self.path.lstat()
        except OSError as exc:
            raise SettingsError(
                "settings upgrade lock changed during save"
            ) from exc
        try:
            _require_private_regular(current, "settings upgrade lock")
        except SettingsError as exc:
            raise SettingsError(
                "settings upgrade lock changed during save"
            ) from exc
        if not _same_file_identity(opened, current):
            raise SettingsError("settings upgrade lock changed during save")
        if self.identity is not None and _identity(opened) != self.identity:
            raise SettingsError("settings upgrade lock changed during save")
        return opened

    def assert_current(self) -> None:
        self._require_current_handle()

    def _open_handle(self) -> None:
        try:
            before = self.path.lstat()
        except FileNotFoundError:
            before = None
        except OSError as exc:
            raise SettingsError(
                "settings upgrade lock could not be inspected"
            ) from exc
        if before is not None:
            _require_private_regular(before, "settings upgrade lock")

        flags = os.O_RDWR
        flags |= getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOINHERIT", 0)
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_NONBLOCK", 0)
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
            opened = self._require_current_handle()
            if before is not None and not _same_file_identity(before, opened):
                raise SettingsError(
                    "settings upgrade lock changed while opening"
                )
            self.identity = _identity(opened)
        except BaseException:
            if self.handle is not None:
                self.handle.close()
                self.handle = None
            else:
                os.close(descriptor)
            self.identity = None
            raise

    def __enter__(self) -> "_SettingsSaveLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._open_handle()
        assert self.handle is not None
        try:
            opened = self._require_current_handle()
            if opened.st_size == 0:
                self.handle.seek(0)
                self.handle.write(b"\0")
                self.handle.flush()
                os.fsync(self.handle.fileno())
                self._require_current_handle()
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
            self._require_current_handle()
            return self
        except BaseException:
            self.handle.close()
            self.handle = None
            self.identity = None
            raise

    def __exit__(self, exc_type, exc, tb) -> None:
        handle = self.handle
        self.handle = None
        self.identity = None
        if handle is None:
            return

        # The protected body remains the transaction authority. In save() it
        # returns only after the canonical settings bytes have been atomically
        # published and all durability/identity checks have completed. A later
        # unlock or close failure cannot undo that publication, so cleanup must
        # not convert durable success into a caller-visible failure. Exceptions
        # raised by the protected body still propagate because __exit__ never
        # returns True.
        try:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
        finally:
            try:
                handle.close()
            except Exception:
                pass


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
    if key in {"sounds", "newgame_animation"}:
        if not isinstance(value, bool):
            raise SettingsError(f"{key} must be boolean")
        return value
    if key == "volume":
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
            raise SettingsError("volume must be an integer in 0..100")
        return value
    if key in {"tick_policy", "low_time_policy"}:
        if value not in _ALLOWED_TICK_POLICY:
            raise SettingsError(f"{key} must be off, my_turn, or both")
        return value
    if key in {"tick_last_seconds", "low_time_seconds"}:
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 3600:
            raise SettingsError(f"{key} must be an integer in 0..3600")
        return value
    if key in _SOUND_VARIANT_KEYS:
        if not isinstance(value, str):
            raise SettingsError("sound variant must be text")
        token = value.strip()
        if (
            not token
            or len(token) > 40
            or token != value
            or any(not (character.isalnum() or character in {"-", "_"}) for character in token)
        ):
            raise SettingsError("sound variant id is invalid")
        return token
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

    def _persist_or_reload(self) -> None:
        """Keep runtime Settings aligned with the actual durable publication."""
        try:
            self.save()
        except Exception:
            # save() can fail before publication (for example upgrade-lock
            # contention) or after publication if a coordination identity check
            # detects an ambiguous race. Reloading is the only truthful runtime
            # state in both cases: it mirrors whatever is actually durable.
            self.load()
            raise

    def set(self, key: str, value: Any) -> None:
        validated = _validated_value(key, value)
        self.data[key] = validated
        self._persist_or_reload()

    def reset(self, key: str | None = None) -> None:
        if key is None:
            self.data = dict(DEFAULTS)
        else:
            if key not in DEFAULTS:
                raise KeyError(f"unknown setting: {key}")
            self.data[key] = DEFAULTS[key]
        self._persist_or_reload()

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
            self._persist_or_reload()
        return warnings

    def save(self) -> None:
        payload = (self.export_json() + "\n").encode("utf-8")
        with _SettingsSaveLock(self.path) as upgrade_lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, raw = tempfile.mkstemp(
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                dir=str(self.path.parent),
            )
            temp: Path | None = Path(raw)
            temp_identity: tuple[int, int] | None = None
            try:
                created = os.fstat(fd)
                _require_private_regular(created, "settings temporary file")
                temp_identity = _identity(created)

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
                    temp_identity = _identity(prepared)

                assert temp is not None
                current = temp.lstat()
                _require_private_regular(current, "settings temporary file")
                if _identity(current) != temp_identity:
                    raise SettingsError(
                        "settings temporary file changed before publication"
                    )

                upgrade_lock.assert_current()
                os.replace(temp, self.path)
                temp = None

                published = self.path.lstat()
                _require_private_regular(
                    published,
                    "settings publication",
                )
                if _identity(published) != temp_identity:
                    raise SettingsError(
                        "settings publication changed before durability confirmation"
                    )
                _fsync_directory(self.path.parent)
                published = self.path.lstat()
                _require_private_regular(
                    published,
                    "settings publication",
                )
                if _identity(published) != temp_identity:
                    raise SettingsError(
                        "settings publication changed before durability confirmation"
                    )
                upgrade_lock.assert_current()
            finally:
                if fd >= 0:
                    os.close(fd)
                if temp is not None and temp_identity is not None:
                    try:
                        _remove_exact_private_file(
                            temp,
                            expected_identity=temp_identity,
                            label="settings temporary file",
                        )
                    except SettingsError:
                        # Never delete a pathname that stopped naming our
                        # private temp inode. Leaving owned crash residue is
                        # safer than deleting foreign bytes.
                        pass