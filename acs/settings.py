from __future__ import annotations

import errno
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import stat
import tempfile
from typing import Any, Mapping


SCHEMA_VERSION = 2
_MAX_SETTINGS_BYTES = 1024 * 1024
_MAX_SETTINGS_JSON_DEPTH = 32
_MAX_SETTINGS_JSON_SEPARATORS = 8192
_MAX_SETTINGS_JSON_OBJECT_MEMBERS = 512
_MAX_SETTINGS_JSON_NUMBER_CHARS = 128

DEFAULTS: dict[str, Any] = {
    "language": "uk",
    "notation": "uk_literal",
    "sounds": True,
    "announce_move_errors": False,
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


class SettingsFutureSchemaError(SettingsError):
    """Raised when settings belong to a newer application schema."""


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


def _require_private_directory(info: os.stat_result, label: str) -> None:
    if stat.S_ISLNK(info.st_mode) or _reparse(info) or not stat.S_ISDIR(info.st_mode):
        raise SettingsError(f"{label} must be one private directory")


def _same_file_version(first: os.stat_result, second: os.stat_result) -> bool:
    return (
        _same_file_identity(first, second)
        and int(first.st_size) == int(second.st_size)
        and int(getattr(first, "st_mtime_ns", 0))
        == int(getattr(second, "st_mtime_ns", 0))
        and int(getattr(first, "st_ctime_ns", 0))
        == int(getattr(second, "st_ctime_ns", 0))
    )


def _settings_text_revision(text: str | None) -> str | None:
    if text is None:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_private_settings_snapshot(
    path: Path,
) -> tuple[str | None, tuple[int, int] | None]:
    """Read one stable private settings snapshot and its exact inode identity."""
    try:
        parent_before = path.parent.lstat()
    except FileNotFoundError:
        return None, None
    except OSError as exc:
        raise SettingsError("settings directory could not be inspected safely") from exc
    _require_private_directory(parent_before, "settings directory")

    try:
        before = path.lstat()
    except FileNotFoundError:
        return None, None
    except OSError as exc:
        raise SettingsError("settings file could not be inspected safely") from exc
    _require_private_regular(before, "settings file")
    if int(before.st_size) > _MAX_SETTINGS_BYTES:
        raise SettingsError("settings file is too large")

    flags = os.O_RDONLY
    flags |= getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOINHERIT", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise SettingsError("settings file could not be opened safely") from exc

    try:
        opened = os.fstat(descriptor)
        _require_private_regular(opened, "settings file")
        if not _same_file_identity(before, opened):
            raise SettingsError("settings file changed while opening")
        if int(opened.st_size) > _MAX_SETTINGS_BYTES:
            raise SettingsError("settings file is too large")

        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(65536, _MAX_SETTINGS_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > _MAX_SETTINGS_BYTES:
                raise SettingsError("settings file is too large")

        after = os.fstat(descriptor)
        _require_private_regular(after, "settings file")
        if not _same_file_version(opened, after) or total != int(after.st_size):
            raise SettingsError("settings file changed while reading")

        try:
            parent_after = path.parent.lstat()
            current = path.lstat()
        except OSError as exc:
            raise SettingsError("settings file changed while reading") from exc
        _require_private_directory(parent_after, "settings directory")
        if not _same_file_identity(parent_before, parent_after):
            raise SettingsError("settings directory changed while reading")
        _require_private_regular(current, "settings file")
        if not _same_file_version(after, current):
            raise SettingsError("settings file changed while reading")
        payload = b"".join(chunks)
    finally:
        os.close(descriptor)

    try:
        return payload.decode("utf-8"), _identity(current)
    except UnicodeDecodeError as exc:
        raise SettingsError("settings file is not valid UTF-8") from exc


def _read_private_settings_text(path: Path) -> str | None:
    """Compatibility wrapper returning only the authenticated settings text."""
    text, _identity_value = _read_private_settings_snapshot(path)
    return text


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
        self.parent_identity: tuple[int, int] | None = None

    def _require_current_parent(self) -> os.stat_result:
        try:
            current = self.path.parent.lstat()
        except OSError as exc:
            raise SettingsError("settings directory changed during save") from exc
        try:
            _require_private_directory(current, "settings directory")
        except SettingsError as exc:
            raise SettingsError("settings directory changed during save") from exc
        if self.parent_identity is not None and _identity(current) != self.parent_identity:
            raise SettingsError("settings directory changed during save")
        return current

    def _require_current_handle(self) -> os.stat_result:
        if self.handle is None:
            raise SettingsError("settings upgrade lock is not open")
        self._require_current_parent()
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
        self._require_current_parent()
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
        parent = self.path.parent.lstat()
        _require_private_directory(parent, "settings directory")
        self.parent_identity = _identity(parent)
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
            self.parent_identity = None
            raise

    def __exit__(self, exc_type, exc, tb) -> None:
        handle = self.handle
        self.handle = None
        self.identity = None
        self.parent_identity = None
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


def _validated_setting_key(key: object) -> str:
    """Return one passive canonical settings key without invoking subclass hooks."""

    if type(key) is not str:
        raise KeyError("unknown setting")
    if key not in DEFAULTS:
        raise KeyError(f"unknown setting: {key}")
    return key


def _validated_value(key: str, value: Any) -> Any:
    key = _validated_setting_key(key)
    if key == "language":
        if type(value) is not str or value not in _ALLOWED_LANGUAGE:
            raise SettingsError("language must be 'uk' or 'en'")
        return value
    if key == "notation":
        if type(value) is not str or value not in _ALLOWED_NOTATION:
            raise SettingsError("notation must be san, uk_literal, or en_literal")
        return value
    if key in {"sounds", "newgame_animation", "announce_move_errors"}:
        if type(value) is not bool:
            raise SettingsError(f"{key} must be boolean")
        return value
    if key == "volume":
        if type(value) is not int or not 0 <= value <= 100:
            raise SettingsError("volume must be an integer in 0..100")
        return value
    if key in {"tick_policy", "low_time_policy"}:
        if type(value) is not str or value not in _ALLOWED_TICK_POLICY:
            raise SettingsError(f"{key} must be off, my_turn, or both")
        return value
    if key in {"tick_last_seconds", "low_time_seconds"}:
        if type(value) is not int or not 0 <= value <= 3600:
            raise SettingsError(f"{key} must be an integer in 0..3600")
        return value
    if key in _SOUND_VARIANT_KEYS:
        if type(value) is not str:
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
        if type(value) is not str:
            raise SettingsError("engine_path must be a string")
        return value
    raise SettingsError(f"validation policy is missing for setting: {key}")


def _validated_import_text(text: object) -> str:
    """Bound direct profile ingress to the same passive UTF-8 envelope as disk."""

    if type(text) is not str:
        raise SettingsError("settings profile must be text")
    # Every Unicode scalar needs at least one UTF-8 byte, so reject an oversized
    # Python string before allocating an encoded copy.
    if len(text) > _MAX_SETTINGS_BYTES:
        raise SettingsError("settings profile is too large")
    try:
        encoded = text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise SettingsError("settings profile is not valid UTF-8") from exc
    if len(encoded) > _MAX_SETTINGS_BYTES:
        raise SettingsError("settings profile is too large")
    return text


def _validate_settings_json_lexical_bounds(text: str) -> None:
    """Reject hostile JSON shape before the recursive stdlib decoder runs."""

    depth = 0
    separators = 0
    in_string = False
    escaped = False
    for character in text:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character in "[{":
            depth += 1
            if depth > _MAX_SETTINGS_JSON_DEPTH:
                raise SettingsError("settings JSON nesting is too deep")
        elif character in "]}":
            if depth:
                depth -= 1
        elif character in ",:":
            separators += 1
            if separators > _MAX_SETTINGS_JSON_SEPARATORS:
                raise SettingsError("settings JSON has too many structural items")


def _reject_nonfinite_settings_json(token: str) -> None:
    raise SettingsError("settings JSON contains a non-finite number")


def _parse_settings_json_int(token: str) -> int:
    if len(token) > _MAX_SETTINGS_JSON_NUMBER_CHARS:
        raise SettingsError("settings JSON number token is too long")
    return int(token)


def _parse_settings_json_float(token: str) -> float:
    if len(token) > _MAX_SETTINGS_JSON_NUMBER_CHARS:
        raise SettingsError("settings JSON number token is too long")
    value = float(token)
    if not math.isfinite(value):
        raise SettingsError("settings JSON contains a non-finite number")
    return value


def _reject_duplicate_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build one passive JSON object while rejecting ambiguous duplicate keys."""

    if len(pairs) > _MAX_SETTINGS_JSON_OBJECT_MEMBERS:
        raise SettingsError("settings JSON object has too many members")
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SettingsError("settings JSON contains a duplicate object key")
        result[key] = value
    return result


def _parse_settings_json(text: str) -> Any:
    """Parse one bounded, unambiguous JSON settings document."""

    _validate_settings_json_lexical_bounds(text)
    return json.loads(
        text,
        object_pairs_hook=_reject_duplicate_json_object,
        parse_constant=_reject_nonfinite_settings_json,
        parse_int=_parse_settings_json_int,
        parse_float=_parse_settings_json_float,
    )


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
        raise SettingsFutureSchemaError(
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
        self._baseline_known = False
        self._baseline_revision: str | None = None
        self._baseline_identity: tuple[int, int] | None = None
        self._write_blocked_reason: str | None = None
        self.load()

    def load(self) -> None:
        self.data = dict(DEFAULTS)
        self.warning = None
        self._baseline_known = False
        self._baseline_revision = None
        self._baseline_identity = None
        self._write_blocked_reason = None
        try:
            text, identity = _read_private_settings_snapshot(self.path)
        except Exception as exc:
            self.warning = f"settings recovery: {exc}"
            return

        self._baseline_known = True
        self._baseline_revision = _settings_text_revision(text)
        self._baseline_identity = identity
        if text is None:
            return

        try:
            raw = _parse_settings_json(text)
            if not isinstance(raw, Mapping):
                raise SettingsError("settings file must contain a JSON object")
            values, migration_warnings = _migrate(raw)
            for key, value in values.items():
                if key not in DEFAULTS:
                    continue
                self.data[key] = _validated_value(key, value)
            if migration_warnings:
                self.warning = "; ".join(migration_warnings)
        except SettingsFutureSchemaError as exc:
            self.data = dict(DEFAULTS)
            self._write_blocked_reason = str(exc)
            self.warning = f"settings recovery: {exc}"
        except Exception as exc:
            self.data = dict(DEFAULTS)
            self.warning = f"settings recovery: {exc}"

    def get(self, key: str, default: Any = None) -> Any:
        if type(key) is not str:
            return default
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
        canonical_key = _validated_setting_key(key)
        validated = _validated_value(canonical_key, value)
        self.data[canonical_key] = validated
        self._persist_or_reload()

    def reset(self, key: str | None = None) -> None:
        if key is None:
            self.data = dict(DEFAULTS)
        else:
            canonical_key = _validated_setting_key(key)
            self.data[canonical_key] = DEFAULTS[canonical_key]
        self._persist_or_reload()

    def to_profile(self) -> dict[str, Any]:
        values = {key: self.data[key] for key in DEFAULTS}
        return {"schema_version": SCHEMA_VERSION, "values": values}

    def export_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_profile(), ensure_ascii=False, indent=indent, sort_keys=True)

    def import_json(self, text: str, *, persist: bool = True) -> tuple[str, ...]:
        if type(persist) is not bool:
            raise SettingsError("settings import persist flag must be boolean")
        raw = _parse_settings_json(_validated_import_text(text))
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
        if not self._baseline_known:
            raise SettingsError(
                "settings write blocked until canonical storage is loaded safely"
            )
        if self._write_blocked_reason is not None:
            raise SettingsError(
                "settings write blocked while a newer schema is present: "
                + self._write_blocked_reason
            )

        payload = (self.export_json() + "\n").encode("utf-8")
        with _SettingsSaveLock(self.path) as upgrade_lock:
            current_text, current_identity = _read_private_settings_snapshot(self.path)
            if (
                _settings_text_revision(current_text) != self._baseline_revision
                or current_identity != self._baseline_identity
            ):
                raise SettingsError(
                    "settings changed since this Settings instance was loaded"
                )

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
                publication_text, publication_identity = _read_private_settings_snapshot(
                    self.path
                )
                if (
                    _settings_text_revision(publication_text) != self._baseline_revision
                    or publication_identity != self._baseline_identity
                ):
                    raise SettingsError(
                        "settings changed during publication preparation"
                    )
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
                self._baseline_known = True
                self._baseline_revision = hashlib.sha256(payload).hexdigest()
                self._baseline_identity = temp_identity
                self._write_blocked_reason = None
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
