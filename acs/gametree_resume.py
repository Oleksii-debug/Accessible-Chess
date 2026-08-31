from __future__ import annotations

"""Durable application-resume state over the canonical GameTree snapshot.

This module deliberately does not parse PGN and does not create another tree.
The persisted chess payload is the versioned :mod:`gametree_snapshot` record;
restore therefore always passes through ``restore_game()``, which in turn uses
the canonical bounded D06 PGN normalization path.  Resume adds only a stable
structural ``GameTreeCursor`` plus generation/CAS publication metadata.

Publication is fail-closed.  A complete JSON envelope is fsynced in the target
directory before an atomic commit primitive is used.  Existing stores require
an exact token from a prior load/save, and cooperating processes serialize the
commit through a sibling OS lock file.  The target is never truncated in place.
"""

from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Iterator

from .gametree import MAX_TREE_NODES, MAX_VARIATION_DEPTH, PgnGame
from .gametree_navigation import (
    GameTreeCursor,
    GameTreeNavigationError,
    VariationStep,
    validate_cursor,
)
from .gametree_snapshot import (
    MAX_SNAPSHOT_RECORD_BYTES,
    GameTreeSnapshot,
    GameTreeSnapshotCode,
    GameTreeSnapshotError,
    restore_game,
    snapshot_from_record,
    snapshot_game,
    snapshot_to_record,
)


GAMETREE_RESUME_SCHEMA_VERSION = 1
MAX_RESUME_RECORD_BYTES = MAX_SNAPSHOT_RECORD_BYTES + 256 * 1024
MAX_RESUME_GENERATION = (1 << 63) - 1
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_RESUME_RECORD_FIELDS = frozenset(
    {"schema_version", "generation", "snapshot", "cursor", "payload_digest"}
)
_CURSOR_FIELDS = frozenset({"line_path", "next_move_index"})
_STEP_FIELDS = frozenset({"parent_move_index", "variation_index"})


class GameTreeResumeCode(str, Enum):
    INVALID_RESUME = "invalid_resume"
    UNSUPPORTED_VERSION = "unsupported_version"
    RESOURCE_LIMIT = "resource_limit"
    SNAPSHOT_REJECTED = "snapshot_rejected"
    CURSOR_REJECTED = "cursor_rejected"
    PAYLOAD_MISMATCH = "payload_mismatch"
    STALE_SNAPSHOT = "stale_snapshot"
    STALE_WRITER = "stale_writer"
    IO_FAILURE = "io_failure"


class GameTreeResumeError(ValueError):
    def __init__(self, message: str, *, code: GameTreeResumeCode) -> None:
        super().__init__(message)
        self.code = GameTreeResumeCode(code)


def _require_digest(
    value: object,
    name: str,
    *,
    code: GameTreeResumeCode = GameTreeResumeCode.INVALID_RESUME,
) -> str:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        raise GameTreeResumeError(
            f"{name} must be a lowercase SHA-256 digest",
            code=code,
        )
    return value


def _canonical_json_bytes(value: object) -> bytes:
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise GameTreeResumeError(
            "resume state cannot be encoded canonically",
            code=GameTreeResumeCode.INVALID_RESUME,
        ) from exc
    return text.encode("utf-8")


def _reject_duplicate_object_pairs(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    record: dict[str, object] = {}
    for key, value in pairs:
        if key in record:
            raise GameTreeResumeError(
                f"duplicate resume JSON field: {key}",
                code=GameTreeResumeCode.INVALID_RESUME,
            )
        record[key] = value
    return record


def _reject_json_constant(value: str) -> object:
    raise GameTreeResumeError(
        f"non-finite JSON constant is forbidden: {value}",
        code=GameTreeResumeCode.INVALID_RESUME,
    )


def _exact_bounded_index(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise GameTreeResumeError(
            f"{name} must be a non-negative exact integer",
            code=GameTreeResumeCode.INVALID_RESUME,
        )
    if value > MAX_TREE_NODES:
        raise GameTreeResumeError(
            f"{name} exceeds the GameTree safety limit",
            code=GameTreeResumeCode.RESOURCE_LIMIT,
        )
    return value


def _cursor_to_record(cursor: GameTreeCursor) -> dict[str, object]:
    if not isinstance(cursor, GameTreeCursor):
        raise GameTreeResumeError(
            "resume cursor must be a GameTreeCursor",
            code=GameTreeResumeCode.CURSOR_REJECTED,
        )
    return {
        "line_path": [
            {
                "parent_move_index": step.parent_move_index,
                "variation_index": step.variation_index,
            }
            for step in cursor.line_path
        ],
        "next_move_index": cursor.next_move_index,
    }


def _cursor_from_record(record: object) -> GameTreeCursor:
    if type(record) is not dict or set(record) != _CURSOR_FIELDS:
        raise GameTreeResumeError(
            "resume cursor record is not canonical",
            code=GameTreeResumeCode.INVALID_RESUME,
        )
    raw_path = record["line_path"]
    if type(raw_path) is not list:
        raise GameTreeResumeError(
            "resume cursor line_path must be an exact list",
            code=GameTreeResumeCode.INVALID_RESUME,
        )
    if len(raw_path) > MAX_VARIATION_DEPTH:
        raise GameTreeResumeError(
            "resume cursor path exceeds the variation-depth safety limit",
            code=GameTreeResumeCode.RESOURCE_LIMIT,
        )
    steps: list[VariationStep] = []
    for raw_step in raw_path:
        if type(raw_step) is not dict or set(raw_step) != _STEP_FIELDS:
            raise GameTreeResumeError(
                "resume cursor path step is not canonical",
                code=GameTreeResumeCode.INVALID_RESUME,
            )
        parent = _exact_bounded_index(
            raw_step["parent_move_index"], "parent_move_index"
        )
        variation = _exact_bounded_index(
            raw_step["variation_index"], "variation_index"
        )
        try:
            steps.append(VariationStep(parent, variation))
        except (TypeError, ValueError, GameTreeNavigationError) as exc:
            raise GameTreeResumeError(
                "resume cursor path step is invalid",
                code=GameTreeResumeCode.INVALID_RESUME,
            ) from exc
    next_move = _exact_bounded_index(record["next_move_index"], "next_move_index")
    try:
        return GameTreeCursor(tuple(steps), next_move)
    except (TypeError, ValueError, GameTreeNavigationError) as exc:
        raise GameTreeResumeError(
            "resume cursor record is invalid",
            code=GameTreeResumeCode.INVALID_RESUME,
        ) from exc


def _resume_payload_record(
    *,
    schema_version: int,
    generation: int,
    snapshot: GameTreeSnapshot,
    cursor: GameTreeCursor,
) -> dict[str, object]:
    return {
        "schema_version": schema_version,
        "generation": generation,
        "snapshot": snapshot_to_record(snapshot),
        "cursor": _cursor_to_record(cursor),
    }


def _resume_payload_digest(
    *,
    schema_version: int,
    generation: int,
    snapshot: GameTreeSnapshot,
    cursor: GameTreeCursor,
) -> str:
    return hashlib.sha256(
        _canonical_json_bytes(
            _resume_payload_record(
                schema_version=schema_version,
                generation=generation,
                snapshot=snapshot,
                cursor=cursor,
            )
        )
    ).hexdigest()


def _map_snapshot_error(exc: GameTreeSnapshotError) -> GameTreeResumeError:
    code = (
        GameTreeResumeCode.RESOURCE_LIMIT
        if exc.code == GameTreeSnapshotCode.RESOURCE_LIMIT
        else GameTreeResumeCode.SNAPSHOT_REJECTED
    )
    return GameTreeResumeError("canonical GameTree snapshot was rejected", code=code)


@dataclass(frozen=True, slots=True)
class GameTreeResumeRecord:
    schema_version: int
    generation: int
    snapshot: GameTreeSnapshot
    cursor: GameTreeCursor
    payload_digest: str

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int:
            raise GameTreeResumeError(
                "schema_version must be an exact integer",
                code=GameTreeResumeCode.INVALID_RESUME,
            )
        if self.schema_version != GAMETREE_RESUME_SCHEMA_VERSION:
            raise GameTreeResumeError(
                "resume schema version is unsupported",
                code=GameTreeResumeCode.UNSUPPORTED_VERSION,
            )
        if (
            type(self.generation) is not int
            or self.generation < 1
            or self.generation > MAX_RESUME_GENERATION
        ):
            raise GameTreeResumeError(
                "resume generation is outside the supported range",
                code=GameTreeResumeCode.INVALID_RESUME,
            )
        if not isinstance(self.snapshot, GameTreeSnapshot):
            raise GameTreeResumeError(
                "resume snapshot must be a GameTreeSnapshot",
                code=GameTreeResumeCode.INVALID_RESUME,
            )
        if not isinstance(self.cursor, GameTreeCursor):
            raise GameTreeResumeError(
                "resume cursor must be a GameTreeCursor",
                code=GameTreeResumeCode.INVALID_RESUME,
            )
        digest = _require_digest(self.payload_digest, "payload_digest")
        expected = _resume_payload_digest(
            schema_version=self.schema_version,
            generation=self.generation,
            snapshot=self.snapshot,
            cursor=self.cursor,
        )
        if digest != expected:
            raise GameTreeResumeError(
                "resume envelope digest does not match",
                code=GameTreeResumeCode.PAYLOAD_MISMATCH,
            )


@dataclass(frozen=True, slots=True)
class GameTreeResumeState:
    game: PgnGame
    cursor: GameTreeCursor
    generation: int
    token: str


def build_resume_record(
    game: PgnGame,
    cursor: GameTreeCursor,
    *,
    generation: int,
) -> GameTreeResumeRecord:
    if not isinstance(game, PgnGame):
        raise TypeError("build_resume_record requires a PgnGame")
    if not isinstance(cursor, GameTreeCursor):
        raise TypeError("build_resume_record requires a GameTreeCursor")
    if type(generation) is not int or generation < 1:
        raise GameTreeResumeError(
            "resume generation must be a positive exact integer",
            code=GameTreeResumeCode.INVALID_RESUME,
        )
    if generation > MAX_RESUME_GENERATION:
        raise GameTreeResumeError(
            "resume generation exceeds the safety limit",
            code=GameTreeResumeCode.RESOURCE_LIMIT,
        )
    try:
        validate_cursor(game, cursor)
    except (TypeError, ValueError, GameTreeNavigationError) as exc:
        raise GameTreeResumeError(
            "resume cursor does not resolve in the canonical GameTree",
            code=GameTreeResumeCode.CURSOR_REJECTED,
        ) from exc
    try:
        snapshot = snapshot_game(game)
    except GameTreeSnapshotError as exc:
        raise _map_snapshot_error(exc) from exc
    digest = _resume_payload_digest(
        schema_version=GAMETREE_RESUME_SCHEMA_VERSION,
        generation=generation,
        snapshot=snapshot,
        cursor=cursor,
    )
    return GameTreeResumeRecord(
        schema_version=GAMETREE_RESUME_SCHEMA_VERSION,
        generation=generation,
        snapshot=snapshot,
        cursor=cursor,
        payload_digest=digest,
    )


def resume_record_to_record(record: GameTreeResumeRecord) -> dict[str, object]:
    if not isinstance(record, GameTreeResumeRecord):
        raise TypeError("resume_record_to_record requires a GameTreeResumeRecord")
    return {
        **_resume_payload_record(
            schema_version=record.schema_version,
            generation=record.generation,
            snapshot=record.snapshot,
            cursor=record.cursor,
        ),
        "payload_digest": record.payload_digest,
    }


def resume_record_from_record(record: object) -> GameTreeResumeRecord:
    if type(record) is not dict:
        raise GameTreeResumeError(
            "resume record must be an exact object",
            code=GameTreeResumeCode.INVALID_RESUME,
        )
    fields = set(record)
    if fields != _RESUME_RECORD_FIELDS:
        raise GameTreeResumeError(
            "resume record fields are not canonical",
            code=GameTreeResumeCode.INVALID_RESUME,
        )
    schema_version = record["schema_version"]
    if type(schema_version) is not int:
        raise GameTreeResumeError(
            "schema_version must be an exact integer",
            code=GameTreeResumeCode.INVALID_RESUME,
        )
    if schema_version != GAMETREE_RESUME_SCHEMA_VERSION:
        raise GameTreeResumeError(
            "resume schema version is unsupported",
            code=GameTreeResumeCode.UNSUPPORTED_VERSION,
        )
    generation = record["generation"]
    if (
        type(generation) is not int
        or generation < 1
        or generation > MAX_RESUME_GENERATION
    ):
        raise GameTreeResumeError(
            "resume generation is outside the supported range",
            code=GameTreeResumeCode.INVALID_RESUME,
        )
    try:
        snapshot = snapshot_from_record(record["snapshot"])
    except GameTreeSnapshotError as exc:
        raise _map_snapshot_error(exc) from exc
    cursor = _cursor_from_record(record["cursor"])
    return GameTreeResumeRecord(
        schema_version=schema_version,
        generation=generation,
        snapshot=snapshot,
        cursor=cursor,
        payload_digest=record["payload_digest"],
    )


def resume_record_to_json(record: GameTreeResumeRecord) -> str:
    payload = _canonical_json_bytes(resume_record_to_record(record))
    if len(payload) > MAX_RESUME_RECORD_BYTES:
        raise GameTreeResumeError(
            "resume JSON exceeds the safety limit",
            code=GameTreeResumeCode.RESOURCE_LIMIT,
        )
    return payload.decode("utf-8")


def resume_record_from_json(text: object) -> GameTreeResumeRecord:
    if not isinstance(text, str) or not text:
        raise GameTreeResumeError(
            "resume JSON must be non-empty text",
            code=GameTreeResumeCode.INVALID_RESUME,
        )
    encoded = text.encode("utf-8")
    if len(encoded) > MAX_RESUME_RECORD_BYTES:
        raise GameTreeResumeError(
            "resume JSON exceeds the safety limit",
            code=GameTreeResumeCode.RESOURCE_LIMIT,
        )
    try:
        record = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_object_pairs,
            parse_constant=_reject_json_constant,
        )
    except GameTreeResumeError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise GameTreeResumeError(
            "resume JSON is malformed",
            code=GameTreeResumeCode.INVALID_RESUME,
        ) from exc
    return resume_record_from_record(record)


def restore_resume_record(
    record: GameTreeResumeRecord,
    *,
    expected_tree_digest: str | None = None,
) -> tuple[PgnGame, GameTreeCursor]:
    if not isinstance(record, GameTreeResumeRecord):
        raise TypeError("restore_resume_record requires a GameTreeResumeRecord")
    if expected_tree_digest is not None:
        expected = _require_digest(expected_tree_digest, "expected_tree_digest")
        if record.snapshot.tree_digest != expected:
            raise GameTreeResumeError(
                "resume snapshot is stale for the expected GameTree",
                code=GameTreeResumeCode.STALE_SNAPSHOT,
            )
    try:
        game = restore_game(record.snapshot)
    except GameTreeSnapshotError as exc:
        raise _map_snapshot_error(exc) from exc
    try:
        validate_cursor(game, record.cursor)
    except (TypeError, ValueError, GameTreeNavigationError) as exc:
        raise GameTreeResumeError(
            "resume cursor does not resolve in the restored canonical GameTree",
            code=GameTreeResumeCode.CURSOR_REJECTED,
        ) from exc
    return game, record.cursor


def _is_reparse_point(st: os.stat_result) -> bool:
    attrs = getattr(st, "st_file_attributes", 0)
    marker = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attrs & marker)


def _validate_regular_path(path: Path, *, allow_missing: bool) -> bool:
    try:
        st = path.lstat()
    except FileNotFoundError:
        if allow_missing:
            return False
        raise GameTreeResumeError(
            "resume store does not exist",
            code=GameTreeResumeCode.IO_FAILURE,
        )
    except OSError as exc:
        raise GameTreeResumeError(
            "resume store metadata could not be read safely",
            code=GameTreeResumeCode.IO_FAILURE,
        ) from exc
    if stat.S_ISLNK(st.st_mode) or _is_reparse_point(st) or not stat.S_ISREG(st.st_mode):
        raise GameTreeResumeError(
            "resume store must be a regular file",
            code=GameTreeResumeCode.IO_FAILURE,
        )
    if st.st_size > MAX_RESUME_RECORD_BYTES + 1:
        raise GameTreeResumeError(
            "resume store exceeds the safety limit",
            code=GameTreeResumeCode.RESOURCE_LIMIT,
        )
    return True


def _read_store_bytes(path: Path) -> bytes:
    _validate_regular_path(path, allow_missing=False)
    try:
        before = path.lstat()
        with path.open("rb") as handle:
            payload = handle.read(MAX_RESUME_RECORD_BYTES + 2)
        after = path.lstat()
    except OSError as exc:
        raise GameTreeResumeError(
            "resume store could not be read safely",
            code=GameTreeResumeCode.IO_FAILURE,
        ) from exc
    if len(payload) > MAX_RESUME_RECORD_BYTES + 1:
        raise GameTreeResumeError(
            "resume store exceeds the safety limit",
            code=GameTreeResumeCode.RESOURCE_LIMIT,
        )
    before_key = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        getattr(before, "st_mtime_ns", None),
    )
    after_key = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        getattr(after, "st_mtime_ns", None),
    )
    if before_key != after_key:
        raise GameTreeResumeError(
            "resume store changed while being read",
            code=GameTreeResumeCode.STALE_WRITER,
        )
    return payload


def _token_for_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _cleanup_redundant_path(path: Path | None) -> None:
    if path is None:
        return
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        try:
            os.unlink(path)
        except OSError:
            pass


def _fsync_directory(directory: Path) -> None:
    if os.name == "nt":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        fd = os.open(directory, flags)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError as exc:
        raise GameTreeResumeError(
            "resume directory durability could not be verified",
            code=GameTreeResumeCode.IO_FAILURE,
        ) from exc


def _reserve_hardlink_snapshot(destination: Path) -> Path:
    for _ in range(8):
        fd, raw_name = tempfile.mkstemp(
            dir=str(destination.parent),
            prefix=destination.name + ".cas-",
            suffix=".bak",
        )
        os.close(fd)
        backup = Path(raw_name)
        backup.unlink()
        try:
            os.link(destination, backup)
            return backup
        except FileExistsError:
            continue
        except OSError as exc:
            raise GameTreeResumeError(
                "resume CAS snapshot could not be created",
                code=GameTreeResumeCode.IO_FAILURE,
            ) from exc
    raise GameTreeResumeError(
        "resume CAS snapshot could not reserve a unique path",
        code=GameTreeResumeCode.IO_FAILURE,
    )


def _publish_new(tmp_path: Path, destination: Path) -> None:
    try:
        os.link(tmp_path, destination)
    except FileExistsError as exc:
        raise GameTreeResumeError(
            "a newer resume store already exists",
            code=GameTreeResumeCode.STALE_WRITER,
        ) from exc
    except OSError as exc:
        raise GameTreeResumeError(
            "resume no-clobber publication failed",
            code=GameTreeResumeCode.IO_FAILURE,
        ) from exc
    _cleanup_redundant_path(tmp_path)


def _publish_update(
    tmp_path: Path,
    destination: Path,
    *,
    expected_token: str,
) -> None:
    current = _read_store_bytes(destination)
    if _token_for_bytes(current) != expected_token:
        raise GameTreeResumeError(
            "resume store changed before publication",
            code=GameTreeResumeCode.STALE_WRITER,
        )
    backup = _reserve_hardlink_snapshot(destination)
    preserve_backup = False
    try:
        if _token_for_bytes(_read_store_bytes(destination)) != expected_token:
            raise GameTreeResumeError(
                "resume store changed before publication",
                code=GameTreeResumeCode.STALE_WRITER,
            )
        if _token_for_bytes(_read_store_bytes(backup)) != expected_token:
            raise GameTreeResumeError(
                "resume store changed before publication",
                code=GameTreeResumeCode.STALE_WRITER,
            )
        try:
            os.replace(tmp_path, destination)
        except OSError as exc:
            raise GameTreeResumeError(
                "resume atomic publication failed",
                code=GameTreeResumeCode.IO_FAILURE,
            ) from exc

        # The backup references the old inode.  An in-place non-cooperating
        # writer that reached it before replace changes this token as well; in
        # that case restore its newer bytes rather than silently clobber them.
        try:
            backup_token = _token_for_bytes(_read_store_bytes(backup))
        except GameTreeResumeError as exc:
            preserve_backup = True
            raise GameTreeResumeError(
                "resume publication could not verify the recovery snapshot",
                code=GameTreeResumeCode.IO_FAILURE,
            ) from exc
        if backup_token != expected_token:
            try:
                os.replace(backup, destination)
            except OSError as exc:
                preserve_backup = True
                raise GameTreeResumeError(
                    "resume concurrent-write rollback failed",
                    code=GameTreeResumeCode.IO_FAILURE,
                ) from exc
            backup = None
            raise GameTreeResumeError(
                "resume store changed during publication",
                code=GameTreeResumeCode.STALE_WRITER,
            )
    finally:
        if backup is not None and not preserve_backup:
            _cleanup_redundant_path(backup)


@contextmanager
def _exclusive_store_lock(destination: Path) -> Iterator[None]:
    lock_path = destination.with_name(destination.name + ".lock")
    if _validate_regular_path(lock_path, allow_missing=True):
        pass
    try:
        handle = lock_path.open("a+b")
    except OSError as exc:
        raise GameTreeResumeError(
            "resume store lock could not be opened",
            code=GameTreeResumeCode.IO_FAILURE,
        ) from exc
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
                os.fsync(handle.fileno())
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            except OSError as exc:
                raise GameTreeResumeError(
                    "resume store lock could not be acquired",
                    code=GameTreeResumeCode.IO_FAILURE,
                ) from exc
            try:
                yield
            finally:
                try:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
        else:
            import fcntl

            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            except OSError as exc:
                raise GameTreeResumeError(
                    "resume store lock could not be acquired",
                    code=GameTreeResumeCode.IO_FAILURE,
                ) from exc
            try:
                yield
            finally:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
    finally:
        handle.close()


class GameTreeResumeStore:
    """Atomic, generation/CAS-protected durable resume store for one GameTree."""

    def __init__(self, path: str | Path) -> None:
        try:
            self._path = Path(path)
        except (TypeError, ValueError) as exc:
            raise GameTreeResumeError(
                "resume store path is invalid",
                code=GameTreeResumeCode.INVALID_RESUME,
            ) from exc

    @property
    def path(self) -> Path:
        return self._path

    def _load_unlocked(
        self,
        *,
        expected_tree_digest: str | None = None,
    ) -> GameTreeResumeState:
        payload = _read_store_bytes(self._path)
        token = _token_for_bytes(payload)
        try:
            text = payload.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise GameTreeResumeError(
                "resume store is not valid UTF-8",
                code=GameTreeResumeCode.INVALID_RESUME,
            ) from exc
        record = resume_record_from_json(text)
        game, cursor = restore_resume_record(
            record,
            expected_tree_digest=expected_tree_digest,
        )
        return GameTreeResumeState(
            game=game,
            cursor=cursor,
            generation=record.generation,
            token=token,
        )

    def load(
        self,
        *,
        expected_tree_digest: str | None = None,
    ) -> GameTreeResumeState:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with _exclusive_store_lock(self._path):
            return self._load_unlocked(expected_tree_digest=expected_tree_digest)

    def save(
        self,
        game: PgnGame,
        cursor: GameTreeCursor,
        *,
        expected_token: str | None = None,
    ) -> GameTreeResumeState:
        if expected_token is not None:
            expected_token = _require_digest(expected_token, "expected_token")
        self._path.parent.mkdir(parents=True, exist_ok=True)

        with _exclusive_store_lock(self._path):
            exists = _validate_regular_path(self._path, allow_missing=True)
            current: GameTreeResumeState | None = None
            if exists:
                # Corrupt/unrestorable authoritative state is never silently
                # overwritten.  A caller must resolve or explicitly remove it.
                current = self._load_unlocked()
                if expected_token is None or current.token != expected_token:
                    raise GameTreeResumeError(
                        "resume store has a newer or unclaimed writer state",
                        code=GameTreeResumeCode.STALE_WRITER,
                    )
                if current.generation >= MAX_RESUME_GENERATION:
                    raise GameTreeResumeError(
                        "resume generation exceeds the safety limit",
                        code=GameTreeResumeCode.RESOURCE_LIMIT,
                    )
                generation = current.generation + 1
            else:
                if expected_token is not None:
                    raise GameTreeResumeError(
                        "resume store disappeared since it was observed",
                        code=GameTreeResumeCode.STALE_WRITER,
                    )
                generation = 1

            record = build_resume_record(game, cursor, generation=generation)
            payload = resume_record_to_json(record).encode("utf-8") + b"\n"
            if len(payload) > MAX_RESUME_RECORD_BYTES + 1:
                raise GameTreeResumeError(
                    "resume store exceeds the safety limit",
                    code=GameTreeResumeCode.RESOURCE_LIMIT,
                )
            desired_token = _token_for_bytes(payload)

            tmp_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    dir=str(self._path.parent),
                    prefix=self._path.name + ".",
                    suffix=".tmp",
                    delete=False,
                ) as handle:
                    tmp_path = Path(handle.name)
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())

                if current is None:
                    _publish_new(tmp_path, self._path)
                    tmp_path = None
                else:
                    _publish_update(
                        tmp_path,
                        self._path,
                        expected_token=current.token,
                    )
                    tmp_path = None
                _fsync_directory(self._path.parent)
            finally:
                _cleanup_redundant_path(tmp_path)

            readback = self._load_unlocked()
            if readback.token != desired_token:
                raise GameTreeResumeError(
                    "resume store changed immediately after publication",
                    code=GameTreeResumeCode.STALE_WRITER,
                )
            if readback.generation != generation:
                raise GameTreeResumeError(
                    "resume generation changed immediately after publication",
                    code=GameTreeResumeCode.STALE_WRITER,
                )
            return readback
