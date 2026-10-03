from __future__ import annotations

"""Durable atomic replay ledger for trusted classroom moderation RPC.

The moderation service owns operation semantics and fingerprints. This module
only persists the reservation/commit state required by that service so retries
and multiple server workers cannot rebind one room-scoped operation id to
different semantics.
"""

from contextlib import closing
from pathlib import Path
import re
import sqlite3

from .classroom_moderation_rpc import ModerationOperationState


_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")
_SCHEMA = """
CREATE TABLE IF NOT EXISTS classroom_moderation_operations (
    room_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    committed INTEGER NOT NULL DEFAULT 0 CHECK (committed IN (0, 1)),
    reservation_owner TEXT,
    PRIMARY KEY (room_id, operation_id),
    CHECK (
        (committed = 0 AND reservation_owner IS NOT NULL)
        OR (committed = 1 AND reservation_owner IS NULL)
    )
)
"""


class ClassroomModerationLedgerError(RuntimeError):
    """Sanitized durable-ledger failure safe for the moderation service boundary."""


class SqliteClassroomModerationLedger:
    """SQLite/WAL implementation of ClassroomModerationOperationLedgerPort."""

    __slots__ = ("_path", "_timeout_seconds")

    def __init__(
        self,
        path: str | Path,
        *,
        timeout_seconds: float = 5.0,
    ) -> None:
        if isinstance(path, Path):
            storage_path = path
        elif type(path) is str and path:
            storage_path = Path(path)
        else:
            raise ClassroomModerationLedgerError("moderation ledger path is invalid")
        if str(storage_path) == ":memory:":
            raise ClassroomModerationLedgerError(
                "moderation ledger requires durable file storage"
            )
        if (
            type(timeout_seconds) not in (int, float)
            or isinstance(timeout_seconds, bool)
            or timeout_seconds <= 0
            or timeout_seconds > 60
        ):
            raise ClassroomModerationLedgerError("moderation ledger timeout is invalid")
        self._path = storage_path
        self._timeout_seconds = float(timeout_seconds)
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with closing(self._connect()) as connection:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute(_SCHEMA)
        except (OSError, sqlite3.Error):
            raise ClassroomModerationLedgerError(
                "moderation ledger initialization failed"
            ) from None

    def __repr__(self) -> str:
        return "SqliteClassroomModerationLedger(path=<redacted>)"

    def operation_state(
        self,
        *,
        room_id: str,
        operation_id: str,
    ) -> ModerationOperationState | None:
        room = _identifier(room_id, "room id")
        operation = _identifier(operation_id, "operation id")
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    """
                    SELECT fingerprint, committed, reservation_owner
                    FROM classroom_moderation_operations
                    WHERE room_id = ? AND operation_id = ?
                    """,
                    (room, operation),
                ).fetchone()
        except sqlite3.Error:
            raise ClassroomModerationLedgerError(
                "moderation ledger read failed"
            ) from None
        return None if row is None else _state(row)

    def reserve(
        self,
        *,
        room_id: str,
        operation_id: str,
        fingerprint: str,
        reservation_owner: str,
    ) -> ModerationOperationState:
        room = _identifier(room_id, "room id")
        operation = _identifier(operation_id, "operation id")
        digest = _fingerprint(fingerprint)
        owner = _identifier(reservation_owner, "reservation owner")
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT OR IGNORE INTO classroom_moderation_operations
                    (
                        room_id,
                        operation_id,
                        fingerprint,
                        committed,
                        reservation_owner
                    )
                VALUES (?, ?, ?, 0, ?)
                """,
                (room, operation, digest, owner),
            )
            row = connection.execute(
                """
                SELECT fingerprint, committed, reservation_owner
                FROM classroom_moderation_operations
                WHERE room_id = ? AND operation_id = ?
                """,
                (room, operation),
            ).fetchone()
            if row is None:
                raise ClassroomModerationLedgerError(
                    "moderation ledger reservation disappeared"
                )
            connection.execute("COMMIT")
            return _state(row)
        except ClassroomModerationLedgerError:
            _rollback(connection)
            raise
        except sqlite3.Error:
            _rollback(connection)
            raise ClassroomModerationLedgerError(
                "moderation ledger reservation failed"
            ) from None
        finally:
            connection.close()

    def commit(
        self,
        *,
        room_id: str,
        operation_id: str,
        fingerprint: str,
        reservation_owner: str,
    ) -> None:
        room = _identifier(room_id, "room id")
        operation = _identifier(operation_id, "operation id")
        digest = _fingerprint(fingerprint)
        owner = _identifier(reservation_owner, "reservation owner")
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT fingerprint, committed, reservation_owner
                FROM classroom_moderation_operations
                WHERE room_id = ? AND operation_id = ?
                """,
                (room, operation),
            ).fetchone()
            if row is None:
                raise ClassroomModerationLedgerError(
                    "moderation ledger operation is not reserved"
                )
            current = _state(row)
            if current.fingerprint != digest:
                raise ClassroomModerationLedgerError(
                    "moderation ledger fingerprint conflict"
                )
            if current.committed:
                connection.execute("COMMIT")
                return
            if current.reservation_owner != owner:
                raise ClassroomModerationLedgerError(
                    "moderation ledger reservation owner conflict"
                )
            cursor = connection.execute(
                """
                UPDATE classroom_moderation_operations
                SET committed = 1, reservation_owner = NULL
                WHERE room_id = ? AND operation_id = ?
                  AND fingerprint = ? AND committed = 0
                  AND reservation_owner = ?
                """,
                (room, operation, digest, owner),
            )
            if cursor.rowcount != 1:
                raise ClassroomModerationLedgerError(
                    "moderation ledger commit lost reservation"
                )
            connection.execute("COMMIT")
        except ClassroomModerationLedgerError:
            _rollback(connection)
            raise
        except sqlite3.Error:
            _rollback(connection)
            raise ClassroomModerationLedgerError(
                "moderation ledger commit failed"
            ) from None
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(
                str(self._path),
                timeout=self._timeout_seconds,
                isolation_level=None,
            )
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute(f"PRAGMA busy_timeout={int(self._timeout_seconds * 1000)}")
            return connection
        except sqlite3.Error:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass
            raise ClassroomModerationLedgerError(
                "moderation ledger storage is unavailable"
            ) from None


def _identifier(value: object, label: str) -> str:
    if type(value) is not str or _IDENTIFIER_RE.fullmatch(value) is None:
        raise ClassroomModerationLedgerError(f"{label} is invalid")
    return value


def _fingerprint(value: object) -> str:
    if type(value) is not str or _FINGERPRINT_RE.fullmatch(value) is None:
        raise ClassroomModerationLedgerError("moderation fingerprint is invalid")
    return value


def _state(row: tuple[object, object, object]) -> ModerationOperationState:
    fingerprint, committed, reservation_owner = row
    if (
        type(fingerprint) is not str
        or _FINGERPRINT_RE.fullmatch(fingerprint) is None
        or type(committed) is not int
        or committed not in (0, 1)
        or (
            committed == 0
            and (
                type(reservation_owner) is not str
                or _IDENTIFIER_RE.fullmatch(reservation_owner) is None
            )
        )
        or (committed == 1 and reservation_owner is not None)
    ):
        raise ClassroomModerationLedgerError("moderation ledger row is invalid")
    return ModerationOperationState(
        fingerprint=fingerprint,
        committed=bool(committed),
        reservation_owner=reservation_owner,
    )


def _rollback(connection: sqlite3.Connection) -> None:
    try:
        connection.execute("ROLLBACK")
    except sqlite3.Error:
        pass


__all__ = [
    "ClassroomModerationLedgerError",
    "SqliteClassroomModerationLedger",
]
