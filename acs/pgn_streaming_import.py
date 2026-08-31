from __future__ import annotations

"""Bounded streaming PGN ingress into the canonical GameTree/Library path.

This module deliberately does not parse SAN, NAGs, RAVs, comments, FEN, or chess
rules. It incrementally frames one PGN game at a time, then delegates every
semantic game to :func:`acs.pgn_roundtrip.parse_pgn_text`. Accepted canonical
``PgnGame`` objects are serialized to a disk-backed temporary spool so a large
multi-game document never needs to exist as one in-memory string or tuple.

Publication remains owned by :class:`acs.library_import_service.LibraryImportService`.
The caller must explicitly choose whether a source is atomic or whether a valid
prefix may be committed after a later malformed/truncated game.
"""

from collections.abc import Callable, Iterator, Sequence
import codecs
from dataclasses import dataclass
from enum import Enum
import hashlib
from pathlib import Path
import tempfile
from typing import BinaryIO, overload

from .gametree import PgnGame, TAG_RE, _brace_comment_state_after_line, serialize_game
from .import_contract import SourceFingerprint, fingerprint, verify_source_unchanged
from .library_import_service import (
    LibraryImportCancelledError,
    LibraryImportControlError,
    LibraryImportProgress,
    LibraryImportResult,
    LibraryImportService,
    LibraryImportStorageError,
)
from .pgn_roundtrip import (
    MAX_PGN_SOURCE_BYTES,
    MAX_PGN_TEXT_CHARS,
    PgnRoundTripError,
    parse_pgn_text,
)


class StreamingPgnFailurePolicy(str, Enum):
    """Explicit publication policy for a source with a later bad game."""

    SOURCE_ATOMIC = "source_atomic"
    COMMIT_ACCEPTED_PREFIX = "commit_accepted_prefix"


class StreamingPgnPhase(str, Enum):
    PARSING = "parsing"
    IMPORTING = "importing"


class StreamingPgnErrorCode(str, Enum):
    INVALID_SOURCE = "invalid_source"
    SOURCE_SIZE_LIMIT = "source_size_limit"
    INVALID_ENCODING = "invalid_encoding"
    GAME_SIZE_LIMIT = "game_size_limit"
    GAME_COUNT_LIMIT = "game_count_limit"
    SPOOL_SIZE_LIMIT = "spool_size_limit"
    MALFORMED_PGN = "malformed_pgn"
    TRUNCATED_PGN = "truncated_pgn"
    SOURCE_CHANGED = "source_changed"
    CANCELLED = "cancelled"
    CONTROL_ERROR = "control_error"
    LIBRARY_ERROR = "library_error"


class StreamingPgnImportError(ValueError):
    """Stable, sanitized streaming-import failure."""

    def __init__(
        self,
        message: str,
        *,
        code: StreamingPgnErrorCode,
        accepted_games: int = 0,
        semantic_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = StreamingPgnErrorCode(code)
        self.accepted_games = accepted_games
        self.semantic_code = semantic_code


class StreamingPgnImportCancelledError(StreamingPgnImportError):
    def __init__(self, *, accepted_games: int = 0) -> None:
        super().__init__(
            "PGN import cancelled",
            code=StreamingPgnErrorCode.CANCELLED,
            accepted_games=accepted_games,
        )


class StreamingPgnImportControlError(StreamingPgnImportError):
    def __init__(self, message: str = "PGN import control callback failed") -> None:
        super().__init__(message, code=StreamingPgnErrorCode.CONTROL_ERROR)


@dataclass(frozen=True, slots=True)
class StreamingPgnLimits:
    """Strict transport/storage limits independent of per-game parser limits."""

    read_chunk_bytes: int = 256 * 1024
    max_source_bytes: int = 4 * 1024 * 1024 * 1024
    max_game_bytes: int = MAX_PGN_SOURCE_BYTES
    max_spool_bytes: int = 8 * 1024 * 1024 * 1024
    max_games: int = 250_000

    def __post_init__(self) -> None:
        for name, value in (
            ("read_chunk_bytes", self.read_chunk_bytes),
            ("max_source_bytes", self.max_source_bytes),
            ("max_game_bytes", self.max_game_bytes),
            ("max_spool_bytes", self.max_spool_bytes),
            ("max_games", self.max_games),
        ):
            if type(value) is not int:
                raise TypeError(f"{name} must be an integer")
            if value < 1:
                raise ValueError(f"{name} must be positive")
        if self.read_chunk_bytes > 8 * 1024 * 1024:
            raise ValueError("read_chunk_bytes exceeds the supported bound")
        if self.max_game_bytes > MAX_PGN_SOURCE_BYTES:
            raise ValueError("max_game_bytes exceeds the canonical per-game parser bound")
        if self.max_games > 1_000_000:
            raise ValueError("max_games exceeds the supported bound")


@dataclass(frozen=True, slots=True)
class StreamingPgnProgress:
    phase: StreamingPgnPhase
    bytes_read: int
    total_bytes: int
    accepted_games: int
    imported_games: int
    total_games: int | None

    def __post_init__(self) -> None:
        if not isinstance(self.phase, StreamingPgnPhase):
            raise TypeError("phase must be a StreamingPgnPhase")
        for name, value in (
            ("bytes_read", self.bytes_read),
            ("total_bytes", self.total_bytes),
            ("accepted_games", self.accepted_games),
            ("imported_games", self.imported_games),
        ):
            if type(value) is not int:
                raise TypeError(f"{name} must be an integer")
            if value < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.bytes_read > self.total_bytes:
            raise ValueError("bytes_read must not exceed total_bytes")
        if self.total_games is not None:
            if type(self.total_games) is not int or self.total_games < 1:
                raise ValueError("total_games must be a positive integer when known")
            if self.imported_games > self.total_games:
                raise ValueError("imported_games must not exceed total_games")


@dataclass(frozen=True, slots=True)
class StreamingPgnImportResult:
    source: SourceFingerprint
    library: LibraryImportResult
    accepted_games: int
    complete: bool
    failure_code: str | None = None

    def __post_init__(self) -> None:
        if type(self.accepted_games) is not int or self.accepted_games < 1:
            raise ValueError("accepted_games must be positive")
        if type(self.complete) is not bool:
            raise TypeError("complete must be a boolean")
        if self.library.game_count != self.accepted_games:
            raise ValueError("Library game count must match accepted game count")
        if self.complete and self.failure_code is not None:
            raise ValueError("complete imports cannot expose a failure code")
        if not self.complete and not self.failure_code:
            raise ValueError("partial imports require a failure code")


CancelCheck = Callable[[], bool]
ProgressCallback = Callable[[StreamingPgnProgress], None]


@dataclass(frozen=True, slots=True)
class _ParseFailure:
    code: str
    public_message: str


class _CanonicalGameSpool(Sequence[PgnGame]):
    """Disk-backed canonical games; reparses each record through the D06 parser."""

    def __init__(self, *, max_bytes: int, cancel_check: CancelCheck | None) -> None:
        self._file: BinaryIO = tempfile.TemporaryFile(mode="w+b")
        self._records: list[tuple[int, int, int]] = []
        self._size = 0
        self._max_bytes = max_bytes
        self._cancel_check = cancel_check
        self._closed = False

    def append(self, game: PgnGame, *, source_index: int) -> None:
        text = serialize_game(game)
        payload = text.encode("utf-8")
        next_size = self._size + len(payload)
        if next_size > self._max_bytes:
            raise StreamingPgnImportError(
                "Canonical PGN spool exceeds the configured safety limit",
                code=StreamingPgnErrorCode.SPOOL_SIZE_LIMIT,
                accepted_games=len(self._records),
            )
        offset = self._file.seek(0, 2)
        self._file.write(payload)
        self._records.append((offset, len(payload), source_index))
        self._size = next_size

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._file.close()

    def __len__(self) -> int:
        return len(self._records)

    @overload
    def __getitem__(self, index: int) -> PgnGame:
        ...

    @overload
    def __getitem__(self, index: slice) -> tuple[PgnGame, ...]:
        ...

    def __getitem__(self, index: int | slice) -> PgnGame | tuple[PgnGame, ...]:
        if isinstance(index, slice):
            return tuple(self[item] for item in range(*index.indices(len(self))))
        if type(index) is not int:
            raise TypeError("game index must be an integer or slice")
        normalized = index if index >= 0 else len(self._records) + index
        if normalized < 0 or normalized >= len(self._records):
            raise IndexError(index)
        _poll_cancel(self._cancel_check, accepted_games=len(self._records))
        offset, length, source_index = self._records[normalized]
        self._file.seek(offset)
        payload = self._file.read(length)
        if len(payload) != length:
            raise RuntimeError("Canonical PGN spool could not be read")
        try:
            text = payload.decode("utf-8")
            games = parse_pgn_text(text, strict=True)
        except Exception as exc:
            raise RuntimeError("Canonical PGN spool failed validation") from exc
        if len(games) != 1:
            raise RuntimeError("Canonical PGN spool record did not contain exactly one game")
        game = games[0]
        game.source_index = source_index
        return game

    def __iter__(self) -> Iterator[PgnGame]:
        for index in range(len(self._records)):
            yield self[index]


class _IncrementalGameFramer:
    """Transport-only line framer sharing canonical D06 tag/comment boundaries."""

    def __init__(self, *, max_game_bytes: int) -> None:
        self._max_game_bytes = max_game_bytes
        self._lines: list[str] = []
        self._bytes = 0
        self._seen_movetext = False
        self._inside_brace_comment = False

    def _reset(self) -> None:
        self._lines = []
        self._bytes = 0
        self._seen_movetext = False
        self._inside_brace_comment = False

    def _flush(self) -> str | None:
        if not self._lines or not any(line.strip() for line in self._lines):
            self._reset()
            return None
        text = "\n".join(self._lines).strip("\n") + "\n"
        self._reset()
        return text

    def feed_line(self, line: str) -> str | None:
        # A header-looking line after movetext is a transport boundary even when
        # malformed. This lets an explicitly selected prefix policy retain the
        # already-complete prior game while the canonical parser rejects the bad
        # next header; no PGN semantics are implemented here.
        header_like = (
            not self._inside_brace_comment and line.lstrip().startswith("[")
        )
        completed: str | None = None
        if self._seen_movetext and header_like:
            completed = self._flush()

        line_bytes = len(line.encode("utf-8")) + 1
        if self._bytes + line_bytes > self._max_game_bytes:
            raise StreamingPgnImportError(
                "PGN game exceeds the configured safety limit",
                code=StreamingPgnErrorCode.GAME_SIZE_LIMIT,
            )
        self._lines.append(line)
        self._bytes += line_bytes

        tag = None if self._inside_brace_comment else TAG_RE.match(line)
        if tag is None and line.strip():
            self._seen_movetext = True
        self._inside_brace_comment = _brace_comment_state_after_line(
            line,
            self._inside_brace_comment,
        )
        return completed

    def finish(self) -> str | None:
        if self._inside_brace_comment:
            raise StreamingPgnImportError(
                "PGN ended inside a brace comment",
                code=StreamingPgnErrorCode.TRUNCATED_PGN,
            )
        return self._flush()


def _validate_callback(value: object, *, name: str) -> None:
    if value is not None and not callable(value):
        raise TypeError(f"{name} must be callable")


def _poll_cancel(cancel_check: CancelCheck | None, *, accepted_games: int) -> None:
    if cancel_check is None:
        return
    try:
        cancelled = cancel_check()
    except StreamingPgnImportCancelledError:
        raise
    except Exception as exc:
        raise StreamingPgnImportControlError(
            "PGN import cancellation check failed"
        ) from exc
    if type(cancelled) is not bool:
        raise StreamingPgnImportControlError("cancel_check must return a boolean")
    if cancelled:
        raise StreamingPgnImportCancelledError(accepted_games=accepted_games)


def _emit_progress(
    progress_callback: ProgressCallback | None,
    progress: StreamingPgnProgress,
) -> None:
    if progress_callback is None:
        return
    try:
        progress_callback(progress)
    except Exception as exc:
        raise StreamingPgnImportControlError(
            "PGN import progress callback failed"
        ) from exc


def _normalize_decoded_newlines(text: str, carry_cr: bool) -> tuple[str, bool]:
    if carry_cr:
        text = "\r" + text
    next_carry = text.endswith("\r")
    if next_carry:
        text = text[:-1]
    return text.replace("\r\n", "\n").replace("\r", "\n"), next_carry


def _semantic_failure(exc: PgnRoundTripError) -> _ParseFailure:
    return _ParseFailure(
        code=f"pgn_{exc.code.value}",
        public_message="PGN contains a malformed or non-round-trippable game",
    )


class StreamingPgnLibraryImporter:
    """Incrementally parse a PGN file and publish canonical games via Library."""

    def __init__(self, library: LibraryImportService) -> None:
        if not isinstance(library, LibraryImportService):
            raise TypeError("library must be a LibraryImportService")
        self._library = library

    def import_file(
        self,
        path: str | Path,
        *,
        failure_policy: StreamingPgnFailurePolicy,
        limits: StreamingPgnLimits | None = None,
        source_name: str | None = None,
        cancel_check: CancelCheck | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> StreamingPgnImportResult:
        if not isinstance(failure_policy, StreamingPgnFailurePolicy):
            raise TypeError("failure_policy must be explicitly selected")
        if limits is None:
            limits = StreamingPgnLimits()
        if not isinstance(limits, StreamingPgnLimits):
            raise TypeError("limits must be StreamingPgnLimits")
        if not isinstance(path, (str, Path)):
            raise TypeError("path must be a filesystem path")
        if source_name is not None:
            if type(source_name) is not str:
                raise TypeError("source_name must be text")
            if not source_name.strip():
                raise ValueError("source_name must not be blank")
        _validate_callback(cancel_check, name="cancel_check")
        _validate_callback(progress_callback, name="progress_callback")
        _poll_cancel(cancel_check, accepted_games=0)

        submitted = Path(path)
        try:
            preliminary_size = submitted.stat().st_size
        except OSError as exc:
            raise StreamingPgnImportError(
                "PGN source is unavailable",
                code=StreamingPgnErrorCode.INVALID_SOURCE,
            ) from exc
        if preliminary_size > limits.max_source_bytes:
            raise StreamingPgnImportError(
                "PGN source exceeds the configured safety limit",
                code=StreamingPgnErrorCode.SOURCE_SIZE_LIMIT,
            )

        try:
            source = fingerprint(submitted, chunk_size=limits.read_chunk_bytes)
        except Exception as exc:
            raise StreamingPgnImportError(
                "PGN source failed read-only provenance validation",
                code=StreamingPgnErrorCode.INVALID_SOURCE,
            ) from exc
        if source.size > limits.max_source_bytes:
            raise StreamingPgnImportError(
                "PGN source exceeds the configured safety limit",
                code=StreamingPgnErrorCode.SOURCE_SIZE_LIMIT,
            )
        _poll_cancel(cancel_check, accepted_games=0)

        spool = _CanonicalGameSpool(
            max_bytes=limits.max_spool_bytes,
            cancel_check=cancel_check,
        )
        try:
            failure = self._stream_source(
                source,
                spool,
                limits=limits,
                cancel_check=cancel_check,
                progress_callback=progress_callback,
            )
            accepted_games = len(spool)
            if accepted_games < 1:
                if failure is not None:
                    raise StreamingPgnImportError(
                        failure.public_message,
                        code=StreamingPgnErrorCode.MALFORMED_PGN,
                        semantic_code=failure.code,
                    )
                raise StreamingPgnImportError(
                    "PGN source contains no complete games",
                    code=StreamingPgnErrorCode.MALFORMED_PGN,
                )

            if failure is not None and failure_policy is StreamingPgnFailurePolicy.SOURCE_ATOMIC:
                raise StreamingPgnImportError(
                    failure.public_message,
                    code=StreamingPgnErrorCode.MALFORMED_PGN,
                    accepted_games=accepted_games,
                    semantic_code=failure.code,
                )

            # Bind publication to the exact bytes fingerprinted before parsing.
            # Prefix publication is never permitted for a source that changed.
            try:
                unchanged = verify_source_unchanged(source, submitted)
            except Exception as exc:
                raise StreamingPgnImportError(
                    "PGN source changed before publication",
                    code=StreamingPgnErrorCode.SOURCE_CHANGED,
                    accepted_games=accepted_games,
                ) from exc
            if not unchanged:
                raise StreamingPgnImportError(
                    "PGN source changed before publication",
                    code=StreamingPgnErrorCode.SOURCE_CHANGED,
                    accepted_games=accepted_games,
                )
            _poll_cancel(cancel_check, accepted_games=accepted_games)

            def library_progress(progress: LibraryImportProgress) -> None:
                _emit_progress(
                    progress_callback,
                    StreamingPgnProgress(
                        phase=StreamingPgnPhase.IMPORTING,
                        bytes_read=source.size,
                        total_bytes=source.size,
                        accepted_games=accepted_games,
                        imported_games=progress.processed_games,
                        total_games=progress.total_games,
                    ),
                )

            try:
                library_result = self._library.import_games(
                    spool,
                    source_name=source_name or Path(source.path).name,
                    source_format="pgn",
                    source_sha256=source.sha256,
                    source_warning_count=1 if failure is not None else 0,
                    cancel_check=cancel_check,
                    progress_callback=library_progress,
                )
            except StreamingPgnImportCancelledError:
                raise
            except LibraryImportCancelledError as exc:
                raise StreamingPgnImportCancelledError(
                    accepted_games=accepted_games
                ) from exc
            except (LibraryImportControlError, StreamingPgnImportControlError) as exc:
                raise StreamingPgnImportControlError() from exc
            except LibraryImportStorageError as exc:
                raise StreamingPgnImportError(
                    "PGN Library publication failed",
                    code=StreamingPgnErrorCode.LIBRARY_ERROR,
                    accepted_games=accepted_games,
                ) from exc

            return StreamingPgnImportResult(
                source=source,
                library=library_result,
                accepted_games=accepted_games,
                complete=failure is None,
                failure_code=None if failure is None else failure.code,
            )
        finally:
            spool.close()

    def _stream_source(
        self,
        source: SourceFingerprint,
        spool: _CanonicalGameSpool,
        *,
        limits: StreamingPgnLimits,
        cancel_check: CancelCheck | None,
        progress_callback: ProgressCallback | None,
    ) -> _ParseFailure | None:
        decoder = codecs.getincrementaldecoder("utf-8-sig")("strict")
        framer = _IncrementalGameFramer(max_game_bytes=limits.max_game_bytes)
        digest = hashlib.sha256()
        bytes_read = 0
        pending_text = ""
        carry_cr = False

        def accept_frame(frame: str) -> _ParseFailure | None:
            if len(spool) >= limits.max_games:
                raise StreamingPgnImportError(
                    "PGN source contains too many games",
                    code=StreamingPgnErrorCode.GAME_COUNT_LIMIT,
                    accepted_games=len(spool),
                )
            if len(frame) > MAX_PGN_TEXT_CHARS:
                raise StreamingPgnImportError(
                    "PGN game exceeds the canonical text safety limit",
                    code=StreamingPgnErrorCode.GAME_SIZE_LIMIT,
                    accepted_games=len(spool),
                )
            try:
                parsed = parse_pgn_text(frame, strict=True)
            except PgnRoundTripError as exc:
                return _semantic_failure(exc)
            if len(parsed) != 1:
                return _ParseFailure(
                    code="pgn_game_boundary_mismatch",
                    public_message="PGN game boundary could not be validated",
                )
            game = parsed[0]
            game.source_index = len(spool)
            spool.append(game, source_index=game.source_index)
            _emit_progress(
                progress_callback,
                StreamingPgnProgress(
                    phase=StreamingPgnPhase.PARSING,
                    bytes_read=bytes_read,
                    total_bytes=source.size,
                    accepted_games=len(spool),
                    imported_games=0,
                    total_games=None,
                ),
            )
            _poll_cancel(cancel_check, accepted_games=len(spool))
            return None

        try:
            with open(source.path, "rb", buffering=0) as handle:
                while True:
                    _poll_cancel(cancel_check, accepted_games=len(spool))
                    chunk = handle.read(limits.read_chunk_bytes)
                    if not chunk:
                        break
                    bytes_read += len(chunk)
                    if bytes_read > source.size or bytes_read > limits.max_source_bytes:
                        raise StreamingPgnImportError(
                            "PGN source changed or exceeded its safety limit while reading",
                            code=StreamingPgnErrorCode.SOURCE_CHANGED,
                            accepted_games=len(spool),
                        )
                    digest.update(chunk)
                    try:
                        decoded = decoder.decode(chunk, final=False)
                    except UnicodeDecodeError as exc:
                        return _ParseFailure(
                            code="pgn_invalid_encoding",
                            public_message="PGN source is not valid UTF-8 text",
                        )
                    normalized, carry_cr = _normalize_decoded_newlines(decoded, carry_cr)
                    pending_text += normalized
                    if len(pending_text) > MAX_PGN_TEXT_CHARS:
                        raise StreamingPgnImportError(
                            "PGN line exceeds the canonical text safety limit",
                            code=StreamingPgnErrorCode.GAME_SIZE_LIMIT,
                            accepted_games=len(spool),
                        )
                    lines = pending_text.split("\n")
                    pending_text = lines.pop()
                    for line in lines:
                        completed = framer.feed_line(line)
                        if completed is not None:
                            failure = accept_frame(completed)
                            if failure is not None:
                                return failure
                    _emit_progress(
                        progress_callback,
                        StreamingPgnProgress(
                            phase=StreamingPgnPhase.PARSING,
                            bytes_read=bytes_read,
                            total_bytes=source.size,
                            accepted_games=len(spool),
                            imported_games=0,
                            total_games=None,
                        ),
                    )

                try:
                    decoded = decoder.decode(b"", final=True)
                except UnicodeDecodeError:
                    return _ParseFailure(
                        code="pgn_invalid_encoding",
                        public_message="PGN source is not valid UTF-8 text",
                    )
                normalized, carry_cr = _normalize_decoded_newlines(decoded, carry_cr)
                pending_text += normalized
                if carry_cr:
                    pending_text += "\n"
                if pending_text:
                    completed = framer.feed_line(pending_text)
                    if completed is not None:
                        failure = accept_frame(completed)
                        if failure is not None:
                            return failure
                try:
                    completed = framer.finish()
                except StreamingPgnImportError as exc:
                    if exc.code is StreamingPgnErrorCode.TRUNCATED_PGN:
                        return _ParseFailure(
                            code="pgn_truncated_comment",
                            public_message="PGN source is truncated",
                        )
                    raise
                if completed is not None:
                    failure = accept_frame(completed)
                    if failure is not None:
                        return failure
        except StreamingPgnImportError:
            raise
        except OSError as exc:
            raise StreamingPgnImportError(
                "PGN source could not be read safely",
                code=StreamingPgnErrorCode.INVALID_SOURCE,
                accepted_games=len(spool),
            ) from exc

        if bytes_read != source.size or digest.hexdigest() != source.sha256:
            raise StreamingPgnImportError(
                "PGN source changed while it was being read",
                code=StreamingPgnErrorCode.SOURCE_CHANGED,
                accepted_games=len(spool),
            )
        return None
