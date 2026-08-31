from __future__ import annotations

"""Presentation-neutral large Library import/storage orchestration.

This service starts after a format owner has already produced canonical ``PgnGame``
objects.  It deliberately does not parse files or PGN text and therefore does not
own D04 import-security policy or D06 PGN semantics.  Its responsibility is the
ACSDB publication boundary: one source and all of its games commit atomically,
with cooperative cancellation, exact count-based progress and provenance-safe
repeated-source idempotency.
"""

from collections.abc import Callable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
import json
import re
import sqlite3
import time

from .acsdb import AcsDatabase
from .gametree import PgnGame, serialize_game

_SQLITE_INTEGER_MAX = (1 << 63) - 1
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_BUSY_RETRY_SLICE_MS = 50


class LibraryImportCancelledError(RuntimeError):
    """Raised when a caller cancels a Library storage operation."""


class LibraryImportControlError(RuntimeError):
    """Raised when a cancellation/progress callback violates its contract."""


class LibraryImportStorageError(RuntimeError):
    """Raised when ACSDB cannot atomically publish the parsed game batch."""


class LibraryImportConflictError(LibraryImportStorageError):
    """Raised when immutable source identity conflicts with stored canonical data."""


@dataclass(frozen=True, slots=True)
class LibraryImportProgress:
    """Exact staging progress for one atomic Library import.

    ``processed_games`` counts games staged in the current transaction. A final
    value equal to ``total_games`` means all rows were staged, not that the
    transaction is already durable; successful method return is the commit signal.
    This distinction prevents a UI from treating SQLite implementation details as
    a fabricated percentage while still providing an honest count denominator.
    A reused source emits only the truthful zero-staged event and returns with
    ``LibraryImportResult.reused`` set instead of fabricating staging progress.
    """

    attempt_id: int
    processed_games: int
    total_games: int

    def __post_init__(self) -> None:
        for name, value in (
            ("attempt_id", self.attempt_id),
            ("processed_games", self.processed_games),
            ("total_games", self.total_games),
        ):
            if type(value) is not int:
                raise TypeError(f"{name} must be an integer")
        if self.attempt_id < 1:
            raise ValueError("attempt_id must be positive")
        if self.total_games < 1:
            raise ValueError("total_games must be positive")
        if not 0 <= self.processed_games <= self.total_games:
            raise ValueError("processed_games must be between zero and total_games")


@dataclass(frozen=True, slots=True)
class LibraryImportResult:
    """Bounded aggregate result for a committed or idempotently reused import.

    Large imports intentionally do not return an unbounded list of every game id.
    Stable keyset/query APIs can enumerate rows later. The first/last ids provide
    compact linkage for diagnostics and tests without scaling result memory with
    database size. ``reused`` is true only when the immutable source identity and
    every canonical stored game matched exactly and no source/game rows were added.
    """

    attempt_id: int
    source_id: int
    game_count: int
    warning_count: int
    first_game_id: int
    last_game_id: int
    reused: bool = False


CancelCheck = Callable[[], bool]
ProgressCallback = Callable[[LibraryImportProgress], None]


class _CallbackConnectionBlocker:
    """Fail closed if an observer re-enters the live ACSDB connection.

    Import callbacks are synchronous observers, not nested database transactions.
    Temporarily publishing this proxy through ``AcsDatabase.conn`` prevents a
    callback from committing, rolling back, closing, or querying the same SQLite
    connection while the importer owns an atomic transaction. The real connection
    object is restored in ``finally`` before import execution resumes.

    Code that retained a raw SQLite connection before entering the service is
    outside the application callback contract; application callers should use the
    ``AcsDatabase`` boundary rather than retaining infrastructure handles.
    """

    _MESSAGE = "ACSDB connection is unavailable inside Library import callbacks"

    def __enter__(self):
        raise RuntimeError(self._MESSAGE)

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def __getattr__(self, name: str):
        raise RuntimeError(self._MESSAGE)


@contextmanager
def _isolated_callback_database(database: AcsDatabase | None):
    if database is None:
        yield
        return
    real_connection = database.conn
    blocker = _CallbackConnectionBlocker()
    database.conn = blocker  # type: ignore[assignment]
    try:
        yield
    finally:
        # Always restore the exact live connection even if hostile callback code
        # attempted to replace the public infrastructure attribute itself.
        database.conn = real_connection


def _validate_callback(value: object, *, name: str) -> None:
    if value is not None and not callable(value):
        raise TypeError(f"{name} must be callable")


def _poll_cancel(
    cancel_check: CancelCheck | None,
    *,
    database: AcsDatabase | None = None,
) -> None:
    if cancel_check is None:
        return
    try:
        with _isolated_callback_database(database):
            cancelled = cancel_check()
    except LibraryImportCancelledError:
        raise
    except Exception as exc:
        raise LibraryImportControlError("Library import cancellation check failed") from exc
    if type(cancelled) is not bool:
        raise LibraryImportControlError("cancel_check must return a boolean")
    if cancelled:
        raise LibraryImportCancelledError("Library import cancelled")


def _emit_progress(
    progress_callback: ProgressCallback | None,
    progress: LibraryImportProgress,
    *,
    database: AcsDatabase | None = None,
) -> None:
    if progress_callback is None:
        return
    try:
        with _isolated_callback_database(database):
            progress_callback(progress)
    except Exception as exc:
        raise LibraryImportControlError("Library import progress callback failed") from exc


def _source_metadata(
    *,
    source_name: object,
    source_format: object,
    source_sha256: object,
) -> tuple[str, str, str]:
    if type(source_name) is not str:
        raise TypeError("source_name must be text")
    if not source_name.strip():
        raise ValueError("source_name must not be blank")
    if type(source_format) is not str:
        raise TypeError("source_format must be text")
    normalized_format = source_format.strip().lower()
    if not normalized_format:
        raise ValueError("source_format must not be blank")
    if type(source_sha256) is not str:
        raise TypeError("source_sha256 must be text")
    if not _SHA256_RE.fullmatch(source_sha256):
        raise ValueError("source_sha256 must be a 64-character hexadecimal digest")
    return source_name, normalized_format, source_sha256.lower()


def _validate_games(games: object) -> tuple[Sequence[PgnGame], int]:
    if isinstance(games, (str, bytes, bytearray)) or not isinstance(games, Sequence):
        raise TypeError("games must be a sequence of PgnGame objects")
    total = len(games)
    if total < 1:
        raise ValueError("games must contain at least one parsed game")
    if total > _SQLITE_INTEGER_MAX:
        raise ValueError("game count exceeds SQLite integer range")
    for game in games:
        if not isinstance(game, PgnGame):
            raise TypeError("games must contain only PgnGame objects")
        source_index = game.source_index
        if type(source_index) is not int:
            raise TypeError("game source_index must be an integer")
        if source_index < 0:
            raise ValueError("game source_index must be non-negative")
        if source_index > _SQLITE_INTEGER_MAX:
            raise ValueError("game source_index exceeds SQLite integer range")
    return games, total


def _validate_source_warning_count(value: object) -> int:
    """Validate source-level warnings before any durable import state exists.

    Format adapters can discover warnings that do not belong to one decoded
    game, for example a skipped record in a multi-game source.  Keeping that
    count separate from ``PgnGame.warnings`` avoids attaching database-level
    diagnostics to an arbitrary game while still making the atomic ACSDB audit
    row and UI completion summary honest.
    """

    if type(value) is not int:
        raise TypeError("source_warning_count must be an integer")
    if not 0 <= value <= _SQLITE_INTEGER_MAX:
        raise ValueError("source_warning_count is outside the supported range")
    return value


def _is_sqlite_busy(exc: sqlite3.OperationalError) -> bool:
    """Classify only SQLite BUSY/LOCKED conditions as retryable contention."""

    code = getattr(exc, "sqlite_errorcode", None)
    if type(code) is int:
        primary = code & 0xFF
        return primary in {
            getattr(sqlite3, "SQLITE_BUSY", 5),
            getattr(sqlite3, "SQLITE_LOCKED", 6),
        }
    # Older Python/SQLite combinations may not expose sqlite_errorcode. Keep the
    # fallback deliberately narrow; the original exception never crosses the
    # public Library-import boundary in either case.
    message = str(exc).strip().lower()
    return message in {"database is locked", "database table is locked"}


def _busy_timeout_ms(connection: sqlite3.Connection) -> int:
    row = connection.execute("PRAGMA busy_timeout").fetchone()
    if row is None:
        return 0
    return max(0, int(row[0]))


def _game_warning_count(games: Sequence[PgnGame]) -> int:
    return sum(1 for game in games if game.warnings)


class LibraryImportService:
    """Atomic ACSDB storage service for already-parsed canonical games."""

    def __init__(self, database: AcsDatabase) -> None:
        if not isinstance(database, AcsDatabase):
            raise TypeError("database must be an AcsDatabase")
        self._db = database

    def _create_attempt_with_cancellable_busy_wait(
        self,
        source_name: str,
        source_format: str,
        source_sha256: str,
        cancel_check: CancelCheck | None,
    ) -> int:
        """Create the durable audit row without hiding cancellation inside BUSY.

        ACSDB's normal connection timeout is intentionally preserved as the total
        contention budget. During this one pre-transaction write we temporarily
        split that budget into short SQLite BUSY waits, polling cooperative
        cancellation between slices. The caller's exact ``busy_timeout`` is always
        restored. Non-BUSY SQLite errors are never retried.
        """

        connection = self._db.conn
        original_timeout_ms = _busy_timeout_ms(connection)
        deadline = time.monotonic() + (original_timeout_ms / 1000.0)
        slice_ms = min(_BUSY_RETRY_SLICE_MS, original_timeout_ms)
        connection.execute(f"PRAGMA busy_timeout = {slice_ms}")
        try:
            while True:
                try:
                    return self._db._create_import_attempt(
                        source_name,
                        source_format,
                        source_sha256,
                    )
                except sqlite3.OperationalError as exc:
                    if not _is_sqlite_busy(exc):
                        raise
                    _poll_cancel(cancel_check, database=self._db)
                    if original_timeout_ms == 0 or time.monotonic() >= deadline:
                        raise
                    remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
                    connection.execute(
                        f"PRAGMA busy_timeout = {min(_BUSY_RETRY_SLICE_MS, remaining_ms)}"
                    )
        finally:
            connection.execute(f"PRAGMA busy_timeout = {original_timeout_ms}")

    def _begin_immediate_with_cancellable_busy_wait(
        self,
        cancel_check: CancelCheck | None,
    ) -> None:
        """Acquire the publication writer lock while preserving cancellation.

        The repeated-source decision and either reuse or publication must happen
        under the same SQLite writer transaction. Otherwise two application
        writers can both observe absence and publish duplicate sources. The
        existing busy-timeout remains the total contention budget but is split into
        small waits so cancellation is still observable while waiting for the lock.
        """

        connection = self._db.conn
        if connection.in_transaction:
            raise RuntimeError("Library import publication cannot start inside a transaction")
        original_timeout_ms = _busy_timeout_ms(connection)
        deadline = time.monotonic() + (original_timeout_ms / 1000.0)
        slice_ms = min(_BUSY_RETRY_SLICE_MS, original_timeout_ms)
        connection.execute(f"PRAGMA busy_timeout = {slice_ms}")
        try:
            while True:
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    return
                except sqlite3.OperationalError as exc:
                    if not _is_sqlite_busy(exc):
                        raise
                    _poll_cancel(cancel_check, database=self._db)
                    if original_timeout_ms == 0 or time.monotonic() >= deadline:
                        raise
                    remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
                    connection.execute(
                        f"PRAGMA busy_timeout = {min(_BUSY_RETRY_SLICE_MS, remaining_ms)}"
                    )
        finally:
            connection.execute(f"PRAGMA busy_timeout = {original_timeout_ms}")

    def _matching_source_id(self, source_format: str, source_sha256: str) -> int | None:
        """Return one immutable source candidate or fail on legacy ambiguity.

        The digest is scoped by normalized source format. Source name is provenance,
        not content identity. Existing duplicate source rows are never silently
        merged or deleted: more than one candidate is ambiguous and fails closed.
        ``NOCASE`` also recognizes legacy hexadecimal/source-format casing without
        mutating those historical rows.
        """

        rows = self._db.conn.execute(
            """SELECT id FROM sources
               WHERE source_format = ? COLLATE NOCASE
                 AND sha256 = ? COLLATE NOCASE
               ORDER BY id
               LIMIT 2""",
            (source_format, source_sha256),
        ).fetchall()
        if not rows:
            return None
        if len(rows) != 1:
            raise LibraryImportConflictError("Library source identity is ambiguous")
        return int(rows[0]["id"])

    def _verify_reusable_source(
        self,
        source_id: int,
        games: Sequence[PgnGame],
    ) -> tuple[int, int]:
        """Prove stored canonical content equals the current decoded batch.

        Comparison streams stored rows in source-index order and uses the existing
        canonical GameTree serializer. No second PGN parser/serializer or unbounded
        database-side identity list is introduced. Any canonical drift for the same
        immutable source identity fails closed rather than silently reusing or
        overwriting old Library truth.
        """

        cursor = self._db.conn.execute(
            """SELECT id, source_index, import_status, warnings_json, pgn_text
               FROM games WHERE source_id=? ORDER BY source_index, id""",
            (source_id,),
        )
        first_game_id: int | None = None
        last_game_id: int | None = None
        for game in games:
            row = cursor.fetchone()
            if row is None:
                raise LibraryImportConflictError(
                    "Library source canonical content differs from existing import"
                )
            expected_status = "warning" if game.warnings else "full"
            expected_warnings = json.dumps(game.warnings, ensure_ascii=False)
            expected_pgn = serialize_game(game)
            if (
                int(row["source_index"]) != game.source_index
                or str(row["import_status"]) != expected_status
                or str(row["warnings_json"]) != expected_warnings
                or str(row["pgn_text"]) != expected_pgn
            ):
                raise LibraryImportConflictError(
                    "Library source canonical content differs from existing import"
                )
            game_id = int(row["id"])
            if first_game_id is None:
                first_game_id = game_id
            last_game_id = game_id
        if cursor.fetchone() is not None or first_game_id is None or last_game_id is None:
            raise LibraryImportConflictError(
                "Library source canonical content differs from existing import"
            )
        return first_game_id, last_game_id

    def import_games(
        self,
        games: Sequence[PgnGame],
        *,
        source_name: str,
        source_format: str,
        source_sha256: str,
        source_warning_count: int = 0,
        cancel_check: CancelCheck | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> LibraryImportResult:
        """Atomically publish or idempotently reuse one parsed source in ACSDB.

        Input validation and an immediate cancellation check happen before the
        durable import-attempt row is created. Every call remains an audit event.
        After that attempt is durable, one cancellable ``BEGIN IMMEDIATE`` owns the
        repeated-source decision and the complete reuse/publication transaction.
        This prevents concurrent writers from both publishing the same immutable
        source.

        Identity is normalized ``(source_format, source_sha256)``. ``source_name``
        remains per-attempt provenance, so the same bytes discovered under another
        filename can reuse existing canonical rows while retaining the new audit
        event. A single existing identity is reusable only after every stored game
        matches source index, import status, warnings and canonical serialized PGN.
        Multiple legacy candidates or semantic drift fail closed; no historical row
        is merged, deleted or overwritten automatically.

        Reuse emits only the truthful zero-staged progress event. Successful return
        with ``result.reused`` is the terminal signal; no fake 100% staging event is
        fabricated. Failed/cancelled attempts remain unlinked and retryable.
        """

        source_name, source_format, source_sha256 = _source_metadata(
            source_name=source_name,
            source_format=source_format,
            source_sha256=source_sha256,
        )
        source_warning_count = _validate_source_warning_count(source_warning_count)
        parsed_games, total_games = _validate_games(games)
        _validate_callback(cancel_check, name="cancel_check")
        _validate_callback(progress_callback, name="progress_callback")
        game_warning_count = _game_warning_count(parsed_games)
        if source_warning_count > _SQLITE_INTEGER_MAX - game_warning_count:
            raise ValueError("combined warning count exceeds SQLite integer range")
        warning_count = source_warning_count + game_warning_count
        _poll_cancel(cancel_check, database=self._db)

        attempt_id: int | None = None
        try:
            attempt_id = self._create_attempt_with_cancellable_busy_wait(
                source_name,
                source_format,
                source_sha256,
                cancel_check,
            )

            _emit_progress(
                progress_callback,
                LibraryImportProgress(attempt_id, 0, total_games),
                database=self._db,
            )
            _poll_cancel(cancel_check, database=self._db)

            try:
                self._begin_immediate_with_cancellable_busy_wait(cancel_check)

                existing_source_id = self._matching_source_id(
                    source_format,
                    source_sha256,
                )
                if existing_source_id is not None:
                    first_game_id, last_game_id = self._verify_reusable_source(
                        existing_source_id,
                        parsed_games,
                    )
                    _poll_cancel(cancel_check, database=self._db)
                    self._db._finish_import_attempt(
                        attempt_id,
                        status="warning" if warning_count else "full",
                        source_id=existing_source_id,
                        game_count=total_games,
                        warning_count=warning_count,
                    )
                    self._db.conn.commit()
                    return LibraryImportResult(
                        attempt_id=attempt_id,
                        source_id=existing_source_id,
                        game_count=total_games,
                        warning_count=warning_count,
                        first_game_id=first_game_id,
                        last_game_id=last_game_id,
                        reused=True,
                    )

                source_id = self._db._insert_source(
                    source_name,
                    source_format,
                    source_sha256,
                )
                first_game_id: int | None = None
                last_game_id: int | None = None
                for processed_games, game in enumerate(parsed_games, start=1):
                    _poll_cancel(cancel_check, database=self._db)
                    status = "warning" if game.warnings else "full"
                    game_id = self._db._insert_game(
                        game,
                        source_id,
                        import_status=status,
                    )
                    if first_game_id is None:
                        first_game_id = game_id
                    last_game_id = game_id
                    _emit_progress(
                        progress_callback,
                        LibraryImportProgress(
                            attempt_id,
                            processed_games,
                            total_games,
                        ),
                        database=self._db,
                    )

                _poll_cancel(cancel_check, database=self._db)
                self._db._finish_import_attempt(
                    attempt_id,
                    status="warning" if warning_count else "full",
                    source_id=source_id,
                    game_count=total_games,
                    warning_count=warning_count,
                )
                self._db.conn.commit()
            except Exception:
                if self._db.conn.in_transaction:
                    self._db.conn.rollback()
                raise

            assert first_game_id is not None and last_game_id is not None
            return LibraryImportResult(
                attempt_id=attempt_id,
                source_id=source_id,
                game_count=total_games,
                warning_count=warning_count,
                first_game_id=first_game_id,
                last_game_id=last_game_id,
                reused=False,
            )
        except LibraryImportCancelledError:
            if attempt_id is not None:
                self._record_failed_attempt(attempt_id, "Library import cancelled")
            raise
        except LibraryImportControlError as exc:
            if attempt_id is not None:
                self._record_failed_attempt(attempt_id, str(exc))
            raise
        except LibraryImportConflictError:
            if attempt_id is not None:
                self._record_failed_attempt(
                    attempt_id,
                    "Library source conflicts with existing canonical import",
                )
            raise
        except Exception as exc:
            if attempt_id is not None:
                self._record_failed_attempt(attempt_id, "Library import failed")
            raise LibraryImportStorageError("Library import failed") from exc

    def _record_failed_attempt(self, attempt_id: int, message: str) -> None:
        """Persist a bounded/sanitized failure only after data rollback."""

        with self._db.conn:
            self._db._finish_import_attempt(
                attempt_id,
                status="failed",
                source_id=None,
                game_count=0,
                warning_count=0,
                error_message=message,
            )
