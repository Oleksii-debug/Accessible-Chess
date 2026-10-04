from __future__ import annotations

import errno
import json
import os
import re
import secrets
import stat
import tempfile
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Mapping


STATS_SCHEMA_VERSION = 1
_MAX_COUNTER = 2**63 - 1
_MAX_STATS_FILE_BYTES = 64 * 1024
_NANOSECONDS_PER_SECOND = 1_000_000_000
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")


def _no_duplicate_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("statistics payload contains duplicate fields")
        result[key] = value
    return result


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
        raise OSError(f"{label} must be one private regular file")


def _require_direct_directory(info: os.stat_result, label: str) -> None:
    if stat.S_ISLNK(info.st_mode) or _reparse(info) or not stat.S_ISDIR(info.st_mode):
        raise OSError(f"{label} must be a direct non-reparse directory")


def _prepare_direct_directory_chain(
    path: Path,
    *,
    label: str,
) -> tuple[Path, tuple[tuple[Path, tuple[int, int]], ...]]:
    """Create missing directories without ever traversing a link/reparse ancestor."""
    absolute = Path(os.path.abspath(path))
    parts = absolute.parts
    if not parts:
        raise OSError(f"{label} has no filesystem anchor")

    current = Path(parts[0])
    snapshot: list[tuple[Path, tuple[int, int]]] = []
    for index, part in enumerate(parts):
        if index:
            current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            if index == 0:
                raise OSError(f"{label} filesystem anchor is missing") from None
            try:
                current.mkdir()
            except FileExistsError:
                pass
            except OSError as exc:
                raise OSError(f"{label} could not be created safely") from exc
            try:
                info = current.lstat()
            except OSError as exc:
                raise OSError(f"{label} could not be inspected safely") from exc
        except OSError as exc:
            raise OSError(f"{label} could not be inspected safely") from exc
        _require_direct_directory(info, label)
        snapshot.append((current, _identity(info)))
    return absolute, tuple(snapshot)


def _verify_direct_directory_chain(
    snapshot: tuple[tuple[Path, tuple[int, int]], ...],
    *,
    label: str,
) -> None:
    for directory, expected_identity in snapshot:
        try:
            current = directory.lstat()
        except OSError as exc:
            raise OSError(f"{label} could not be re-inspected safely") from exc
        _require_direct_directory(current, label)
        if _identity(current) != expected_identity:
            raise OSError(f"{label} changed unexpectedly")


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
        raise OSError("statistics directory could not be synchronized") from exc
    try:
        try:
            os.fsync(descriptor)
        except OSError as exc:
            if os.name != "nt" and exc.errno not in {errno.EINVAL, errno.ENOTSUP}:
                raise OSError("statistics directory could not be synchronized") from exc
    finally:
        os.close(descriptor)


def _remove_exact_private_file(
    path: Path,
    *,
    expected_identity: tuple[int, int],
    label: str,
) -> None:
    """Delete only the exact private inode created by this statistics writer."""
    try:
        before = path.lstat()
    except OSError as exc:
        raise OSError(f"{label} could not be inspected safely") from exc
    _require_private_regular(before, label)
    if _identity(before) != expected_identity:
        raise OSError(f"{label} changed unexpectedly")

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
        raise OSError(f"{label} cleanup quarantine could not be allocated")

    try:
        os.replace(path, quarantine)
    except OSError as exc:
        raise OSError(f"{label} could not be quarantined safely") from exc

    moved = quarantine.lstat()
    _require_private_regular(moved, f"{label} quarantine")
    if _identity(moved) != expected_identity:
        raise OSError(f"{label} changed during cleanup")
    try:
        quarantine.unlink()
    except OSError as exc:
        raise OSError(f"{label} could not be removed safely") from exc
    _fsync_directory(path.parent)


def normalize_installation_id(value: object) -> str:
    if type(value) is not str:
        raise ValueError("installation_id must be a bounded opaque identifier")
    normalized = value.strip().lower()
    if not _ID_RE.fullmatch(normalized):
        raise ValueError("installation_id must be a bounded opaque identifier")
    return normalized


def _integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    if value < 0 or value > _MAX_COUNTER:
        raise ValueError(f"{field_name} must be between 0 and {_MAX_COUNTER}")
    return value


@dataclass(frozen=True)
class UsageStatisticsSnapshot:
    installation_id: str
    session_seconds: int = 0
    sessions_started: int = 0
    games_started: int = 0
    games_completed: int = 0
    exercises_attempted: int = 0
    exercises_completed: int = 0
    classroom_seconds: int = 0
    classroom_sessions: int = 0
    feature_uses: int = 0
    schema_version: int = STATS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if isinstance(self.schema_version, bool) or self.schema_version != STATS_SCHEMA_VERSION:
            raise ValueError("unsupported statistics schema")
        object.__setattr__(self, "installation_id", normalize_installation_id(self.installation_id))
        for name in (
            "session_seconds",
            "sessions_started",
            "games_started",
            "games_completed",
            "exercises_attempted",
            "exercises_completed",
            "classroom_seconds",
            "classroom_sessions",
            "feature_uses",
        ):
            object.__setattr__(self, name, _integer(getattr(self, name), name))
        if self.games_completed > self.games_started:
            raise ValueError("games_completed cannot exceed games_started")
        if self.exercises_completed > self.exercises_attempted:
            raise ValueError("exercises_completed cannot exceed exercises_attempted")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "installation_id": self.installation_id,
            "session_seconds": self.session_seconds,
            "sessions_started": self.sessions_started,
            "games_started": self.games_started,
            "games_completed": self.games_completed,
            "exercises_attempted": self.exercises_attempted,
            "exercises_completed": self.exercises_completed,
            "classroom_seconds": self.classroom_seconds,
            "classroom_sessions": self.classroom_sessions,
            "feature_uses": self.feature_uses,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "UsageStatisticsSnapshot":
        allowed = {
            "schema_version",
            "installation_id",
            "session_seconds",
            "sessions_started",
            "games_started",
            "games_completed",
            "exercises_attempted",
            "exercises_completed",
            "classroom_seconds",
            "classroom_sessions",
            "feature_uses",
        }
        actual = set(payload)
        unknown = actual - allowed
        missing = allowed - actual
        if unknown:
            raise ValueError("statistics payload contains unknown fields")
        if missing:
            raise ValueError("statistics payload is missing required fields")
        return cls(
            installation_id=payload["installation_id"],
            session_seconds=payload["session_seconds"],
            sessions_started=payload["sessions_started"],
            games_started=payload["games_started"],
            games_completed=payload["games_completed"],
            exercises_attempted=payload["exercises_attempted"],
            exercises_completed=payload["exercises_completed"],
            classroom_seconds=payload["classroom_seconds"],
            classroom_sessions=payload["classroom_sessions"],
            feature_uses=payload["feature_uses"],
            schema_version=payload["schema_version"],
        )


class AggregateUsageStatistics:
    """Aggregate counters only; never accepts chess/document/communication payloads."""

    def __init__(self, snapshot: UsageStatisticsSnapshot) -> None:
        if type(snapshot) is not UsageStatisticsSnapshot:
            raise ValueError("snapshot must be UsageStatisticsSnapshot")
        self._snapshot = snapshot

    @property
    def snapshot(self) -> UsageStatisticsSnapshot:
        return self._snapshot

    def start_session(self) -> UsageStatisticsSnapshot:
        return self._advance(sessions_started=1)

    def add_session_seconds(self, seconds: int) -> UsageStatisticsSnapshot:
        return self._advance(session_seconds=_integer(seconds, "seconds"))

    def start_game(self) -> UsageStatisticsSnapshot:
        return self._advance(games_started=1)

    def complete_game(self) -> UsageStatisticsSnapshot:
        if self._snapshot.games_completed >= self._snapshot.games_started:
            raise ValueError("cannot complete a game that was not started")
        return self._advance(games_completed=1)

    def attempt_exercise(self) -> UsageStatisticsSnapshot:
        return self._advance(exercises_attempted=1)

    def complete_exercise(self) -> UsageStatisticsSnapshot:
        if self._snapshot.exercises_completed >= self._snapshot.exercises_attempted:
            raise ValueError("cannot complete an exercise that was not attempted")
        return self._advance(exercises_completed=1)

    def start_classroom(self) -> UsageStatisticsSnapshot:
        return self._advance(classroom_sessions=1)

    def add_classroom_seconds(self, seconds: int) -> UsageStatisticsSnapshot:
        return self._advance(classroom_seconds=_integer(seconds, "seconds"))

    def record_feature_use(self) -> UsageStatisticsSnapshot:
        return self._advance(feature_uses=1)

    def _advance(self, **deltas: int) -> UsageStatisticsSnapshot:
        values: dict[str, int] = {}
        for name, delta in deltas.items():
            current = getattr(self._snapshot, name)
            if delta > _MAX_COUNTER - current:
                raise ValueError(f"{name} counter overflow")
            values[name] = current + delta
        self._snapshot = replace(self._snapshot, **values)
        return self._snapshot


class ActiveSessionClock:
    """Counts only foreground-active monotonic time into aggregate session seconds."""

    def __init__(self, *, now_ns: Callable[[], int] = time.monotonic_ns) -> None:
        if not callable(now_ns):
            raise ValueError("now_ns must be callable")
        self._now_ns = now_ns
        self._active_since_ns: int | None = None
        self._unreported_ns = 0

    @property
    def is_active(self) -> bool:
        return self._active_since_ns is not None

    def _read_now(self) -> int:
        value = self._now_ns()
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("now_ns must return a non-negative integer")
        return value

    def resume(self) -> bool:
        if self._active_since_ns is not None:
            return False
        self._active_since_ns = self._read_now()
        return True

    def checkpoint(self, statistics: AggregateUsageStatistics) -> int:
        """Publish whole active seconds while keeping the session active."""
        return self._publish(statistics, remain_active=True)

    def suspend(self, statistics: AggregateUsageStatistics) -> int:
        """Publish whole active seconds and stop counting until the next resume."""
        return self._publish(statistics, remain_active=False)

    def _publish(
        self,
        statistics: AggregateUsageStatistics,
        *,
        remain_active: bool,
    ) -> int:
        if type(statistics) is not AggregateUsageStatistics:
            raise ValueError("statistics must be AggregateUsageStatistics")
        started = self._active_since_ns
        if started is None:
            return 0
        now = self._read_now()
        if now < started:
            raise ValueError("monotonic clock moved backwards")
        total_ns = self._unreported_ns + (now - started)
        whole_seconds, remainder_ns = divmod(total_ns, _NANOSECONDS_PER_SECOND)
        if whole_seconds:
            statistics.add_session_seconds(whole_seconds)
        self._unreported_ns = remainder_ns
        self._active_since_ns = now if remain_active else None
        return whole_seconds


class UsageStatisticsStore:
    """Atomic local snapshot store. Invalid data resets locally without exposing exception text."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.recovered_invalid_data = False

    def load(self, installation_id: str) -> UsageStatisticsSnapshot:
        normalized = normalize_installation_id(installation_id)
        self.recovered_invalid_data = False
        if not self.path.exists():
            return UsageStatisticsSnapshot(normalized)
        try:
            with self.path.open("rb") as handle:
                encoded = handle.read(_MAX_STATS_FILE_BYTES + 1)
            if len(encoded) > _MAX_STATS_FILE_BYTES:
                raise ValueError("statistics payload exceeds the supported size")
            raw = json.loads(
                encoded.decode("utf-8", errors="strict"),
                object_pairs_hook=_no_duplicate_object,
            )
            if not isinstance(raw, Mapping):
                raise ValueError("statistics payload must be an object")
            snapshot = UsageStatisticsSnapshot.from_dict(raw)
            if snapshot.installation_id != normalized:
                raise ValueError("statistics belong to another installation")
            return snapshot
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
            self.recovered_invalid_data = True
            return UsageStatisticsSnapshot(normalized)

    def save(self, snapshot: UsageStatisticsSnapshot) -> None:
        if type(snapshot) is not UsageStatisticsSnapshot:
            raise ValueError("snapshot must be UsageStatisticsSnapshot")
        parent, directory_snapshot = _prepare_direct_directory_chain(
            self.path.parent,
            label="statistics directory",
        )
        target = parent / self.path.name
        _verify_direct_directory_chain(
            directory_snapshot,
            label="statistics directory",
        )
        encoded = json.dumps(
            snapshot.as_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ) + "\n"
        fd, raw_tmp = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            dir=parent,
        )
        tmp: Path | None = Path(raw_tmp)
        temp_identity: tuple[int, int] | None = None
        try:
            created = os.fstat(fd)
            _require_private_regular(created, "statistics temporary file")
            temp_identity = _identity(created)

            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                fd = -1
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
                prepared = os.fstat(handle.fileno())
                _require_private_regular(prepared, "statistics temporary file")
                if not _same_file_identity(created, prepared):
                    raise OSError("statistics temporary file changed while being prepared")
                temp_identity = _identity(prepared)

            assert tmp is not None
            _verify_direct_directory_chain(
                directory_snapshot,
                label="statistics directory",
            )
            current = tmp.lstat()
            _require_private_regular(current, "statistics temporary file")
            if _identity(current) != temp_identity:
                raise OSError("statistics temporary file changed before publication")

            os.replace(tmp, target)
            tmp = None

            _verify_direct_directory_chain(
                directory_snapshot,
                label="statistics directory",
            )
            published = target.lstat()
            _require_private_regular(published, "statistics publication")
            if _identity(published) != temp_identity:
                raise OSError("statistics publication changed before durability confirmation")
            _fsync_directory(parent)
            _verify_direct_directory_chain(
                directory_snapshot,
                label="statistics directory",
            )
            published = target.lstat()
            _require_private_regular(published, "statistics publication")
            if _identity(published) != temp_identity:
                raise OSError("statistics publication changed before durability confirmation")
        finally:
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
            if tmp is not None and temp_identity is not None:
                try:
                    _remove_exact_private_file(
                        tmp,
                        expected_identity=temp_identity,
                        label="statistics temporary file",
                    )
                except OSError:
                    # Never delete a pathname that stopped naming our private
                    # temp inode. Leaving owned crash residue is safer than
                    # deleting foreign bytes.
                    pass
