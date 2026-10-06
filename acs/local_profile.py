from __future__ import annotations

from contextlib import contextmanager

import json
import os
import re
import secrets
import tempfile
import threading
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 1
MAX_PROFILE_BYTES = 16 * 1024
MAX_DISPLAY_NAME_CHARS = 80
_PROFILE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_ALIAS_RE = re.compile(r"^Player-[0-9A-F]{8}$")
_REQUIRED_FIELDS = frozenset(
    {"schema_version", "profile_id", "display_name", "generated_alias", "revision"}
)
_PROCESS_MUTATION_LOCKS: dict[str, threading.RLock] = {}
_PROCESS_MUTATION_LOCKS_GUARD = threading.Lock()


def _process_mutation_lock(path: Path) -> threading.RLock:
    key = os.path.normcase(os.path.abspath(os.fspath(path)))
    with _PROCESS_MUTATION_LOCKS_GUARD:
        lock = _PROCESS_MUTATION_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _PROCESS_MUTATION_LOCKS[key] = lock
        return lock


class LocalProfileError(ValueError):
    """Base error for local-profile persistence and validation failures."""


class UnsafeLocalProfilePath(LocalProfileError):
    """The profile or recovery path is unsafe for local identity persistence."""


class UnsupportedLocalProfileSchema(LocalProfileError):
    """The profile uses a newer schema and must not be silently downgraded."""


class LocalProfileDurabilityUnknownError(LocalProfileError):
    """Atomic profile publication happened, but durable confirmation failed."""


class LocalProfileConflict(LocalProfileError):
    """A stale in-memory profile attempted to overwrite newer durable state."""


@dataclass(frozen=True, slots=True)
class LocalProfile:
    schema_version: int
    profile_id: str
    display_name: str
    generated_alias: bool
    revision: int

    def renamed(self, display_name: str) -> "LocalProfile":
        return replace(
            self,
            display_name=_normalize_display_name(display_name, allow_blank=False),
            generated_alias=False,
            revision=self.revision + 1,
        )


def _reject_duplicate_object_pairs(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise LocalProfileError(f"duplicate profile field: {key}")
        result[key] = value
    return result


def _normalize_display_name(value: str, *, allow_blank: bool) -> str:
    if not isinstance(value, str):
        raise LocalProfileError("display name must be text")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise LocalProfileError("display name contains control characters")
    normalized = " ".join(value.split())
    if not normalized and not allow_blank:
        raise LocalProfileError("display name must not be blank")
    if len(normalized) > MAX_DISPLAY_NAME_CHARS:
        raise LocalProfileError("display name is too long")
    return normalized


def _generate_alias() -> str:
    # Deliberately generated from cryptographic randomness only. Never derive a
    # visible identity from OS username, hostname, e-mail, IP address or device ID.
    return f"Player-{secrets.token_hex(4).upper()}"


def new_local_profile(display_name: str | None = None) -> LocalProfile:
    normalized = "" if display_name is None else _normalize_display_name(display_name, allow_blank=True)
    generated_alias = not normalized
    if generated_alias:
        normalized = _generate_alias()
    return LocalProfile(
        schema_version=SCHEMA_VERSION,
        profile_id=secrets.token_hex(16),
        display_name=normalized,
        generated_alias=generated_alias,
        revision=1,
    )


def _validate_profile(profile: LocalProfile) -> LocalProfile:
    if type(profile.schema_version) is not int:
        raise LocalProfileError("schema version must be an integer")
    if profile.schema_version > SCHEMA_VERSION:
        raise UnsupportedLocalProfileSchema("profile schema is newer than this application")
    if profile.schema_version != SCHEMA_VERSION:
        raise LocalProfileError("unsupported profile schema")
    if not isinstance(profile.profile_id, str) or not _PROFILE_ID_RE.fullmatch(profile.profile_id):
        raise LocalProfileError("invalid profile identifier")
    display_name = _normalize_display_name(profile.display_name, allow_blank=False)
    if display_name != profile.display_name:
        raise LocalProfileError("display name is not canonical")
    if type(profile.generated_alias) is not bool:
        raise LocalProfileError("generated_alias must be boolean")
    if profile.generated_alias and not _ALIAS_RE.fullmatch(profile.display_name):
        raise LocalProfileError("generated alias has invalid format")
    if type(profile.revision) is not int or profile.revision < 1:
        raise LocalProfileError("revision must be a positive integer")
    return profile


def parse_local_profile_bytes(data: bytes) -> LocalProfile:
    if not isinstance(data, (bytes, bytearray)):
        raise LocalProfileError("profile payload must be bytes")
    raw = bytes(data)
    if not raw:
        raise LocalProfileError("profile payload is empty")
    if len(raw) > MAX_PROFILE_BYTES:
        raise LocalProfileError("profile payload is too large")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise LocalProfileError("profile payload is not valid UTF-8") from exc
    try:
        payload = json.loads(text, object_pairs_hook=_reject_duplicate_object_pairs)
    except LocalProfileError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError, RecursionError) as exc:
        raise LocalProfileError("profile payload is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise LocalProfileError("profile payload root must be an object")
    keys = frozenset(payload)
    if keys != _REQUIRED_FIELDS:
        missing = sorted(_REQUIRED_FIELDS - keys)
        extra = sorted(keys - _REQUIRED_FIELDS)
        detail = []
        if missing:
            detail.append("missing=" + ",".join(missing))
        if extra:
            detail.append("extra=" + ",".join(extra))
        raise LocalProfileError("profile fields are invalid" + (": " + "; ".join(detail) if detail else ""))
    schema = payload["schema_version"]
    if type(schema) is not int:
        raise LocalProfileError("schema version must be an integer")
    if schema > SCHEMA_VERSION:
        raise UnsupportedLocalProfileSchema("profile schema is newer than this application")
    return _validate_profile(
        LocalProfile(
            schema_version=schema,
            profile_id=payload["profile_id"],
            display_name=payload["display_name"],
            generated_alias=payload["generated_alias"],
            revision=payload["revision"],
        )
    )


def serialize_local_profile(profile: LocalProfile) -> bytes:
    valid = _validate_profile(profile)
    payload = {
        "display_name": valid.display_name,
        "generated_alias": valid.generated_alias,
        "profile_id": valid.profile_id,
        "revision": valid.revision,
        "schema_version": valid.schema_version,
    }
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


_MOVEFILE_REPLACE_EXISTING = 0x00000001
_MOVEFILE_WRITE_THROUGH = 0x00000008


def _replace_profile_path(source: Path, destination: Path) -> None:
    """Atomically publish one prepared local-profile file with durability intent."""
    if os.name != "nt":
        os.replace(source, destination)
        return

    import ctypes

    move_file_ex = ctypes.WinDLL("kernel32", use_last_error=True).MoveFileExW
    move_file_ex.argtypes = (
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_uint32,
    )
    move_file_ex.restype = ctypes.c_int
    if not move_file_ex(
        os.fspath(source),
        os.fspath(destination),
        _MOVEFILE_REPLACE_EXISTING | _MOVEFILE_WRITE_THROUGH,
    ):
        error_code = ctypes.get_last_error()
        raise OSError(error_code, "durable local-profile replacement failed")


def _sync_profile_publication(path: Path) -> None:
    """Confirm the published namespace entry reached stable storage."""
    if os.name == "nt":
        # MoveFileExW WRITE_THROUGH is the namespace durability barrier. Re-open
        # the file and fsync it as a second content barrier before acknowledgement.
        flags = os.O_RDWR | getattr(os, "O_BINARY", 0)
        no_follow = getattr(os, "O_NOFOLLOW", 0)
        if no_follow:
            flags |= no_follow
        fd = os.open(path, flags)
        try:
            opened = os.fstat(fd)
            current = path.stat(follow_symlinks=False)
            if not os.path.samestat(opened, current):
                raise OSError("published local-profile path changed before durability sync")
            os.fsync(fd)
        finally:
            os.close(fd)
        return

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    directory_fd = os.open(os.fspath(path.parent), flags)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


class LocalProfileStore:
    """Crash-safe local identity storage with one durable recovery copy.

    Loading never rewrites source bytes. A parseable newer-schema primary blocks
    fallback so an older backup cannot silently downgrade identity state. Recovery
    publication is explicit through ``repair_from_backup``.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.backup_path = self.path.with_name(self.path.name + ".backup")
        self.lock_path = self.path.with_name(self.path.name + ".lock")

    @contextmanager
    def _mutation_lock(self):
        """Serialize profile mutations across threads, windows and processes.

        The process-local lock makes same-process callers deterministic on every
        platform. The stable sibling file lock is the cross-process authority and
        is intentionally separate from the atomically replaced profile file.
        No profile data is written to the lock file.
        """
        process_lock = _process_mutation_lock(self.lock_path)
        with process_lock:
            try:
                self.lock_path.parent.mkdir(parents=True, exist_ok=True)
            except OSError:
                raise LocalProfileError("local profile mutation lock is unavailable") from None
            if self.lock_path.is_symlink():
                raise UnsafeLocalProfilePath("profile mutation lock must not be a symbolic link")
            flags = os.O_RDWR | os.O_CREAT
            no_follow = getattr(os, "O_NOFOLLOW", 0)
            if no_follow:
                flags |= no_follow
            try:
                fd = os.open(self.lock_path, flags, 0o600)
            except OSError:
                raise LocalProfileError("local profile mutation lock is unavailable") from None

            locked = False
            try:
                # Reject a link swapped into place around open where the platform
                # can still report it. POSIX O_NOFOLLOW also closes the open-time
                # symlink race.
                if self.lock_path.is_symlink():
                    raise UnsafeLocalProfilePath("profile mutation lock must not be a symbolic link")
                try:
                    os.lseek(fd, 0, os.SEEK_SET)
                    if os.name == "nt":
                        import msvcrt

                        msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(fd, fcntl.LOCK_EX)
                except OSError:
                    raise LocalProfileError("local profile mutation lock is unavailable") from None
                locked = True
                yield
            finally:
                if locked:
                    try:
                        os.lseek(fd, 0, os.SEEK_SET)
                        if os.name == "nt":
                            import msvcrt

                            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                        else:
                            import fcntl

                            fcntl.flock(fd, fcntl.LOCK_UN)
                    except OSError:
                        # The durable mutation result is already decided. Advisory
                        # lock cleanup must not turn a committed identity update
                        # into a caller-visible failure.
                        pass
                try:
                    os.close(fd)
                except OSError:
                    # Descriptor close is cleanup only; process teardown also
                    # releases the advisory lock. Never falsify commit state.
                    pass

    @staticmethod
    def _read_bounded(path: Path) -> bytes:
        if path.is_symlink():
            raise UnsafeLocalProfilePath("profile path must not be a symbolic link")

        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        no_follow = getattr(os, "O_NOFOLLOW", 0)
        if no_follow:
            flags |= no_follow
        fd = -1
        chunks: list[bytes] = []
        try:
            fd = os.open(path, flags)
            opened = os.fstat(fd)
            current = path.stat(follow_symlinks=False)
            if not os.path.samestat(opened, current):
                raise UnsafeLocalProfilePath("profile path changed while being opened")

            remaining = MAX_PROFILE_BYTES + 1
            while remaining:
                block = os.read(fd, remaining)
                if not block:
                    break
                chunks.append(block)
                remaining -= len(block)

            # The descriptor is the data authority, but the pathname must still
            # identify that same file after the read. Atomic replacement by a
            # concurrent/non-cooperating writer therefore fails closed instead of
            # returning bytes from a path that no longer owns them.
            opened_after = os.fstat(fd)
            current_after = path.stat(follow_symlinks=False)
            if not os.path.samestat(opened_after, current_after):
                raise UnsafeLocalProfilePath("profile path changed while being read")
        except UnsafeLocalProfilePath:
            raise
        except OSError:
            if path.is_symlink():
                raise UnsafeLocalProfilePath("profile path must not be a symbolic link") from None
            raise LocalProfileError("profile state cannot be read") from None
        finally:
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    # Descriptor close is cleanup only. The bounded read and path
                    # identity decision above already determine the caller result.
                    pass

        data = b"".join(chunks)
        if len(data) > MAX_PROFILE_BYTES:
            raise LocalProfileError("profile payload is too large")
        return data

    @classmethod
    def _read_profile(cls, path: Path) -> LocalProfile:
        return parse_local_profile_bytes(cls._read_bounded(path))

    def load(self) -> LocalProfile | None:
        primary_exists = self.path.exists() or self.path.is_symlink()
        backup_exists = self.backup_path.exists() or self.backup_path.is_symlink()
        if not primary_exists and not backup_exists:
            return None

        primary_error: LocalProfileError | None = None
        if primary_exists:
            try:
                return self._read_profile(self.path)
            except (UnsafeLocalProfilePath, UnsupportedLocalProfileSchema):
                # Unsafe paths and future schemas are authority failures, not
                # ordinary corruption eligible for recovery fallback.
                raise
            except LocalProfileError as exc:
                primary_error = exc

        if backup_exists:
            try:
                return self._read_profile(self.backup_path)
            except (UnsafeLocalProfilePath, UnsupportedLocalProfileSchema):
                raise
            except LocalProfileError as backup_error:
                raise LocalProfileError("local profile and recovery copy are unreadable") from backup_error

        raise LocalProfileError("local profile is unreadable and has no recovery copy") from primary_error

    def create(self, display_name: str | None = None) -> LocalProfile:
        with self._mutation_lock():
            if self.path.exists() or self.path.is_symlink() or self.backup_path.exists() or self.backup_path.is_symlink():
                # Do not fabricate a new identity over unknown/corrupt persisted bytes.
                existing = self.load()
                if existing is not None:
                    raise LocalProfileConflict("local profile already exists")
            profile = new_local_profile(display_name)
            self._publish(profile, expected_revision=None, allow_initial=True)
            return profile

    def rename(self, current: LocalProfile, display_name: str) -> LocalProfile:
        _validate_profile(current)
        with self._mutation_lock():
            durable = self.load()
            if durable is None:
                raise LocalProfileConflict("local profile no longer exists")
            if durable.profile_id != current.profile_id or durable.revision != current.revision:
                raise LocalProfileConflict("local profile changed since it was read")
            updated = current.renamed(display_name)
            self._publish(updated, expected_revision=current.revision, allow_initial=False)
            return updated

    def repair_from_backup(self) -> LocalProfile:
        """Explicitly restore a verified recovery copy as the primary profile.

        A valid primary is returned unchanged. A parseable newer primary still
        blocks recovery so an old backup can never silently downgrade identity.
        """
        with self._mutation_lock():
            primary_exists = self.path.exists() or self.path.is_symlink()
            if primary_exists:
                try:
                    return self._read_profile(self.path)
                except (UnsafeLocalProfilePath, UnsupportedLocalProfileSchema):
                    raise
                except LocalProfileError:
                    pass

            if not (self.backup_path.exists() or self.backup_path.is_symlink()):
                raise LocalProfileError("no verified local-profile recovery copy is available")
            backup_bytes = self._read_bounded(self.backup_path)
            recovered = parse_local_profile_bytes(backup_bytes)
            self._atomic_replace_bytes(self.path, backup_bytes)
            # Read back the publication instead of assuming replace preserved bytes.
            published_bytes = self._read_bounded(self.path)
            if published_bytes != backup_bytes:
                raise LocalProfileError("local profile recovery readback mismatch")
            published = parse_local_profile_bytes(published_bytes)
            if published != recovered:
                raise LocalProfileError("local profile recovery semantic mismatch")
            return published

    def _assert_safe_target(self, path: Path) -> None:
        if path.is_symlink():
            raise UnsafeLocalProfilePath("profile path must not be a symbolic link")

    def _atomic_replace_bytes(self, target: Path, payload: bytes) -> None:
        self._assert_safe_target(target)
        temp_name: str | None = None
        published = False
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=target.name + ".",
                suffix=".tmp",
                dir=target.parent,
                delete=False,
            ) as handle:
                temp_name = handle.name
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())

            _replace_profile_path(Path(temp_name), target)
            temp_name = None
            published = True
            try:
                _sync_profile_publication(target)
                visible = self._read_bounded(target)
                if visible != payload:
                    raise LocalProfileError(
                        "local profile canonical storage changed after publication"
                    )
            except Exception:
                # The stable public error must not retain raw filesystem paths or
                # platform diagnostics through exception chaining.
                raise LocalProfileDurabilityUnknownError(
                    "local profile was published but durable canonical storage could not be confirmed"
                ) from None
        except LocalProfileDurabilityUnknownError:
            raise
        except OSError:
            if published:
                raise LocalProfileDurabilityUnknownError(
                    "local profile was published but durable canonical storage could not be confirmed"
                ) from None
            raise LocalProfileError("local profile could not be saved") from None
        finally:
            if temp_name is not None:
                try:
                    os.unlink(temp_name)
                except FileNotFoundError:
                    pass
                except OSError:
                    pass

    def _publish(self, profile: LocalProfile, *, expected_revision: int | None, allow_initial: bool) -> None:
        payload = serialize_local_profile(profile)
        primary_exists = self.path.exists() or self.path.is_symlink()
        backup_exists = self.backup_path.exists() or self.backup_path.is_symlink()

        if not primary_exists:
            if backup_exists:
                # A recovery copy is durable identity state; never overwrite it as a new profile.
                recovered = self._read_profile(self.backup_path)
                if not allow_initial or recovered is not None:
                    raise LocalProfileConflict("recovery copy exists without primary profile")
            if not allow_initial:
                raise LocalProfileConflict("local profile no longer exists")
            self._atomic_replace_bytes(self.path, payload)
            return

        try:
            primary_bytes = self._read_bounded(self.path)
            durable = parse_local_profile_bytes(primary_bytes)
        except (UnsafeLocalProfilePath, UnsupportedLocalProfileSchema):
            raise
        except LocalProfileError as primary_error:
            # Preserve a known-good recovery copy, but never overwrite corrupt primary state.
            if backup_exists:
                self._read_profile(self.backup_path)
            raise LocalProfileError("refusing to overwrite unreadable local profile") from primary_error

        if expected_revision is None or durable.revision != expected_revision or durable.profile_id != profile.profile_id:
            raise LocalProfileConflict("local profile changed since it was read")
        if profile.revision != durable.revision + 1:
            raise LocalProfileConflict("profile revision is not the next durable revision")

        # Publish the verified current primary as recovery first. If the new primary
        # replace then fails, at least one verified copy of the old identity remains.
        self._atomic_replace_bytes(self.backup_path, primary_bytes)
        self._atomic_replace_bytes(self.path, payload)
