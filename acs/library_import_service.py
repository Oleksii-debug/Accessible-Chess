from __future__ import annotations

"""Presentation-neutral large Library import/storage orchestration.

This service starts after a format owner has already produced canonical ``PgnGame``
objects.  It deliberately does not parse files or PGN text and therefore does not
own D04 import-security policy or D06 PGN semantics.  Its responsibility is the
ACSDB publication boundary: one source and all of its games commit atomically,
with cooperative cancellation and exact count-based progress.
"""

from collections.abc import Callable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
import re

from .acsdb import AcsDatabase
from .gametree import PgnGame

_SQLITE_INTEGER_MAX = (1 << 63) - 1
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class LibraryImportCancelledError(RuntimeError):
    """Raised when a caller cancels a Library storage operation."""


class LibraryImportControlError(RuntimeError):
    """Raised when a cancellation/progress callback violates its contract."""


class LibraryImportStorageError(RuntimeError):
    """Raised when ACSDB cannot atomically publish the parsed game batch."""


@dataclass(frozen=True, slots=True)
class LibraryImportProgress:
    """Exact staging progress for one atomic Library import.

    ``processed_games`` counts games staged in the current transaction.  A final
    value equal to ``total_games`` means all rows were staged, not that the
    transaction is already durable; successful method return is the commit signal.
    This distinction prevents a UI from treating SQLite implementation details as
    a fabricated percentage while still providing an honest count denominator.
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
    """Bounded aggregate result for a committed import.

    Large imports intentionally do not return an unbounded list of every game id.
    Stable keyset/query APIs can enumerate rows later.  The first/last ids provide
    compact linkage for diagnostics and tests without scaling result memory with
    database size.
    """

    attempt_id: int
    source_id: int
    game_count: int
    warning_count: int
    first_game_id: int
    last_game_id: int


CancelCheck = Callable[[], bool]
ProgressCallback = Callable[[LibraryImportProgress], None]


class _CallbackConnectionBlocker:
    """Fail closed if an observer re-enters the live ACSDB connection.

    Import callbacks are synchronous observers, not nested database transactions.
    Temporarily publishing this proxy through ``AcsDatabase.conn`` prevents a
    callback from committing, rolling back, closing, or querying the same SQLite
    connection while the importer owns an atomic transaction.  The real connection
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


class LibraryImportService:
    """Atomic ACSDB storage service for already-parsed canonical games."""

    def __init__(self, database: AcsDatabase) -> None:
        if not isinstance(database, AcsDatabase):
            raise TypeError("database must be an AcsDatabase")
        self._db = database

    def import_games(
        self,
        games: Sequence[PgnGame],
        *,
        source_name: str,
        source_format: str,
        source_sha256: str,
        cancel_check: CancelCheck | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> LibraryImportResult:
        """Atomically publish one parsed source into ACSDB.

        Input validation and an immediate cancellation check happen before the
        durable import-attempt row is created. Once an attempt exists, any later
        cancellation, callback failure, uniqueness failure, or SQLite/storage
        error rolls back the source and every game row. The attempt itself is
        retained as a sanitized ``failed`` audit record with no linked source.

        Cancellation/progress callbacks are observers. While either callback is
        executing, the live ``AcsDatabase.conn`` handle is replaced by a fail-closed
        proxy so callback re-entry cannot commit or roll back the importer's SQLite
        transaction. The exact connection is restored before execution resumes.
        """

        source_name, source_format, source_sha256 = _source_metadata(
            source_name=source_name,
            source_format=source_format,
            source_sha256=source_sha256,
        )
        parsed_games, total_games = _validate_games(games)
        _validate_callback(cancel_check, name="cancel_check")
        _validate_callback(progress_callback, name="progress_callback")
        _poll_cancel(cancel_check, database=self._db)

        attempt_id = self._db._create_import_attempt(
            source_name,
            source_format,
            source_sha256,
        )

        try:
            _emit_progress(
                progress_callback,
                LibraryImportProgress(attempt_id, 0, total_games),
                database=self._db,
            )
            _poll_cancel(cancel_check, database=self._db)

            warning_count = 0
            first_game_id: int | None = None
            last_game_id: int | None = None

            with self._db.conn:
                source_id = self._db._insert_source(
                    source_name,
                    source_format,
                    source_sha256,
                )
                for processed_games, game in enumerate(parsed_games, start=1):
                    _poll_cancel(cancel_check, database=self._db)
                    status = "warning" if game.warnings else "full"
                    game_id = self._db._insert_game(
                        game,
                        source_id,
                        import_status=status,
                    )
                    if status == "warning":
                        warning_count += 1
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

                # A cancellation arriving after the final insert must still roll
                # the complete transaction back rather than publish a partial or
                # unwanted source at the commit boundary.
                _poll_cancel(cancel_check, database=self._db)
                self._db._finish_import_attempt(
                    attempt_id,
                    status="warning" if warning_count else "full",
                    source_id=source_id,
                    game_count=total_games,
                    warning_count=warning_count,
                )

            assert first_game_id is not None and last_game_id is not None
            return LibraryImportResult(
                attempt_id=attempt_id,
                source_id=source_id,
                game_count=total_games,
                warning_count=warning_count,
                first_game_id=first_game_id,
                last_game_id=last_game_id,
            )
        except LibraryImportCancelledError:
            self._record_failed_attempt(attempt_id, "Library import cancelled")
            raise
        except LibraryImportControlError as exc:
            self._record_failed_attempt(attempt_id, str(exc))
            raise
        except Exception as exc:
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
