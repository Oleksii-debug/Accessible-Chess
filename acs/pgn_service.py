from __future__ import annotations

"""Safe file-level PGN services for Accessible Chess.

This module is deliberately presentation-neutral. It connects the structural
GameTree parser/serializer to real files without teaching the UI about file
encoding, provenance fingerprints, concurrent modification checks, or atomic
replacement.

The source PGN is read-only during inspection/open. Saving always writes a
complete temporary file in the destination directory and then publishes that
complete file through a commit primitive appropriate to the requested safety
contract.
"""

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat
import tempfile
from typing import Callable, Iterable, TextIO

from .gametree import PgnGame, parse_games, serialize_game
from .import_contract import (
    ImportQuality,
    ImportReport,
    ImportedRecord,
    SourceFingerprint,
    _open_readonly_no_reparse,
    _publish_opened_fingerprint,
    _validate_source_path,
    fingerprint,
)
from .pgn_roundtrip import PgnRoundTripError, PgnRoundTripErrorCode, parse_pgn_text


MAX_PGN_SOURCE_BYTES = 64 * 1024 * 1024

_RESOURCE_LIMIT_CODES = frozenset(
    {
        PgnRoundTripErrorCode.BYTE_SIZE_LIMIT,
        PgnRoundTripErrorCode.TEXT_SIZE_LIMIT,
        PgnRoundTripErrorCode.TOKEN_SIZE_LIMIT,
        PgnRoundTripErrorCode.TOKEN_COUNT_LIMIT,
        PgnRoundTripErrorCode.COMMENT_SIZE_LIMIT,
        PgnRoundTripErrorCode.TAG_SIZE_LIMIT,
        PgnRoundTripErrorCode.TAG_COUNT_LIMIT,
        PgnRoundTripErrorCode.GAME_COUNT_LIMIT,
    }
)


class PgnFileError(RuntimeError):
    """Base error for safe PGN file operations."""


class PgnSourceChangedError(PgnFileError):
    """Raised when a file changes while it is being read."""


class PgnResourceLimitError(PgnFileError):
    """Raised when an external PGN exceeds the bounded import contract."""


class PgnConcurrentWriteError(PgnFileError):
    """Raised when optimistic overwrite protection detects a newer source."""


class PgnUnsafePathError(PgnFileError):
    """Raised when export would traverse filesystem indirection."""


class PgnPublicationUnverifiedError(PgnFileError):
    """Raised after publication when final destination provenance is unverified.

    The atomic publication primitive has already crossed the point where the
    destination may have changed. Callers must therefore not describe this as a
    pre-publication save failure or blindly retry against stale provenance.
    """


def _same_direct_path(left: str | Path, right: str | Path) -> bool:
    """Compare direct path spellings with platform path/case normalization."""

    def key(value: str | Path) -> str:
        return os.path.normcase(
            os.path.abspath(os.fspath(Path(value).expanduser()))
        )

    return key(left) == key(right)


@dataclass(frozen=True)
class PgnOpenResult:
    source: SourceFingerprint
    games: tuple[PgnGame, ...]
    global_warnings: tuple[str, ...] = ()

    @property
    def total_games(self) -> int:
        return len(self.games)

    @property
    def warning_games(self) -> int:
        return sum(1 for game in self.games if game.warnings)


class PgnFileImporter:
    """Read-only PGN importer adapter for ImportRegistry preflight/reporting."""

    format_name = "PGN"
    suffixes = (".pgn",)

    def inspect(self, path: Path) -> ImportReport:
        opened = open_pgn(path)
        report = ImportReport(source=opened.source, format_name=self.format_name)
        report.global_warnings.extend(opened.global_warnings)
        if not opened.games:
            report.add(
                ImportedRecord(
                    source_record_id="source",
                    quality=ImportQuality.DAMAGED,
                    message="PGN contains no parseable games.",
                )
            )
            return report

        lossy_source = any(
            warning.startswith("Invalid UTF-8 bytes were replaced")
            for warning in opened.global_warnings
        )
        legacy_windows_1251 = any(
            warning.startswith("Legacy Windows-1251 PGN was decoded losslessly")
            for warning in opened.global_warnings
        )
        for game in opened.games:
            warnings = list(game.warnings)
            if lossy_source:
                warnings.append("Source text required lossy UTF-8 replacement during decoding.")
            if legacy_windows_1251:
                warnings.append(
                    "Source text was decoded losslessly from legacy Windows-1251."
                )
            report.add(
                ImportedRecord(
                    source_record_id=str(game.source_index),
                    quality=ImportQuality.WARNING if warnings else ImportQuality.FULL,
                    message="PGN game parsed structurally.",
                    warnings=tuple(warnings),
                )
            )
        return report


def _is_reparse_point(st: os.stat_result) -> bool:
    attrs = getattr(st, "st_file_attributes", 0)
    marker = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attrs & marker)


def _reject_export_indirection(path: Path) -> None:
    """Fail closed if any existing submitted path component is indirect."""

    absolute = path.absolute()
    parts = absolute.parts
    if not parts:
        raise PgnUnsafePathError("PGN export destination is invalid")

    current = Path(parts[0])
    for part in parts[1:]:
        current = current / part
        try:
            current_stat = current.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise PgnUnsafePathError("PGN export path could not be validated safely") from exc
        if stat.S_ISLNK(current_stat.st_mode) or _is_reparse_point(current_stat):
            raise PgnUnsafePathError("PGN export path must not traverse filesystem indirection")


def _bounded_source_size(path: Path) -> int | None:
    try:
        size = path.lstat().st_size
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise PgnFileError("PGN source is unavailable") from exc
    if size > MAX_PGN_SOURCE_BYTES:
        raise PgnResourceLimitError(
            f"PGN source exceeds the {MAX_PGN_SOURCE_BYTES}-byte safety limit"
        )
    return size


def _source_identity(st: os.stat_result) -> tuple[int, int]:
    return int(st.st_dev), int(st.st_ino)


def _export_parent_identity(path: Path) -> tuple[int, int]:
    """Bind publication to one direct destination-directory object."""

    try:
        current = path.lstat()
    except OSError as exc:
        raise PgnUnsafePathError("PGN export directory could not be bound safely") from exc
    if (
        not stat.S_ISDIR(current.st_mode)
        or stat.S_ISLNK(current.st_mode)
        or _is_reparse_point(current)
    ):
        raise PgnUnsafePathError("PGN export parent must be a direct directory")
    return _source_identity(current)


def _assert_bound_export_parent(
    path: Path,
    expected_identity: tuple[int, int],
) -> None:
    if _export_parent_identity(path) != expected_identity:
        raise PgnUnsafePathError("PGN export directory changed during save")


def _open_direct_source(path: Path):
    """Open one submitted source through the canonical no-follow source primitive."""

    try:
        descriptor = _open_readonly_no_reparse(path)
    except ValueError as exc:
        raise PgnFileError("PGN source must be a direct regular file") from exc
    except OSError as exc:
        raise PgnFileError("PGN source could not be opened safely") from exc

    try:
        return os.fdopen(descriptor, "rb", closefd=True)
    except BaseException:
        os.close(descriptor)
        raise


def _opened_source_identity(handle: object) -> tuple[int, int] | None:
    """Return the real opened object identity; `None` is a focused test-double seam."""

    try:
        fileno = handle.fileno()  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        return None
    try:
        opened = os.fstat(fileno)
    except OSError as exc:
        raise PgnSourceChangedError("PGN source identity could not be verified") from exc
    if not stat.S_ISREG(opened.st_mode):
        raise PgnSourceChangedError("PGN source changed while being opened")
    return _source_identity(opened)


def _assert_bound_source_path(path: Path, expected_identity: tuple[int, int]) -> None:
    """Require the public path to still name the held direct regular-file object."""

    try:
        _, current = _validate_source_path(path)
    except (OSError, ValueError) as exc:
        raise PgnSourceChangedError("PGN source changed while being read") from exc
    if _source_identity(current) != expected_identity:
        raise PgnSourceChangedError("PGN source changed while being read")


def _rehash_open_source(handle: object) -> tuple[str, int]:
    """Re-hash the exact held source object with a finite second pass."""

    try:
        handle.seek(0)  # type: ignore[attr-defined]
    except (AttributeError, OSError, ValueError) as exc:
        raise PgnSourceChangedError("PGN source could not be revalidated") from exc

    digest = hashlib.sha256()
    total = 0
    while True:
        remaining = MAX_PGN_SOURCE_BYTES + 1 - total
        if remaining <= 0:
            raise PgnResourceLimitError("PGN source exceeds the safety limit")
        try:
            chunk = handle.read(min(1024 * 1024, remaining))  # type: ignore[attr-defined]
        except OSError as exc:
            raise PgnSourceChangedError("PGN source could not be revalidated") from exc
        if not chunk:
            return digest.hexdigest(), total
        if not isinstance(chunk, bytes):
            raise PgnSourceChangedError("PGN source verification returned unsupported payload")
        total += len(chunk)
        if total > MAX_PGN_SOURCE_BYTES:
            raise PgnResourceLimitError("PGN source exceeds the safety limit")
        digest.update(chunk)


_WINDOWS_1251_PGN_HEADER_ANCHORS = (
    b"[event",
    b"[site",
    b"[date",
    b"[round",
    b"[white",
    b"[black",
    b"[result",
    b"[fen",
    b"[setup",
)
_WINDOWS_1251_CYRILLIC_BYTES = frozenset((*range(0xC0, 0x100), 0xA8, 0xB8))


def _looks_like_windows_1251_pgn_bytes(payload: bytes) -> bool:
    """Gate legacy Cyrillic decoding without hiding arbitrary invalid UTF-8."""

    if not payload or b"\x00" in payload:
        return False
    lowered = payload.lower()
    if not any(anchor in lowered for anchor in _WINDOWS_1251_PGN_HEADER_ANCHORS):
        return False
    previous_cyrillic = False
    for value in payload:
        current_cyrillic = value in _WINDOWS_1251_CYRILLIC_BYTES
        if current_cyrillic and previous_cyrillic:
            return True
        previous_cyrillic = current_cyrillic
    return False


def _read_text_snapshot(path: Path) -> tuple[SourceFingerprint, str, bool, bool]:
    submitted = Path(path)
    try:
        absolute, path_before = _validate_source_path(submitted)
    except ValueError as exc:
        raise PgnFileError("PGN source must be a direct regular file") from exc
    except OSError as exc:
        raise PgnFileError("PGN source is unavailable") from exc
    if path_before.st_size > MAX_PGN_SOURCE_BYTES:
        raise PgnResourceLimitError(
            f"PGN source exceeds the {MAX_PGN_SOURCE_BYTES}-byte safety limit"
        )

    source: SourceFingerprint
    try:
        with _open_direct_source(absolute) as handle:
            opened_identity = _opened_source_identity(handle)

            if opened_identity is None:
                # Focused bounded-text test doubles do not expose a descriptor.
                # Preserve that seam without using it in production file reads.
                try:
                    before = fingerprint(absolute)
                except (OSError, ValueError) as exc:
                    raise PgnFileError("PGN source could not be fingerprinted safely") from exc
                payload = handle.read(MAX_PGN_SOURCE_BYTES + 1)
                try:
                    after = fingerprint(absolute)
                except (OSError, ValueError) as exc:
                    raise PgnSourceChangedError("PGN source changed while being read") from exc
                if before.size != after.size or before.sha256 != after.sha256:
                    raise PgnSourceChangedError("PGN changed while being read")
                source = before
            else:
                expected_identity = _source_identity(path_before)
                if opened_identity != expected_identity:
                    raise PgnSourceChangedError("PGN source changed while being opened")

                try:
                    fd_before = os.fstat(handle.fileno())
                except (AttributeError, OSError, ValueError) as exc:
                    raise PgnSourceChangedError(
                        "PGN source identity could not be verified"
                    ) from exc
                if (
                    not stat.S_ISREG(fd_before.st_mode)
                    or _source_identity(fd_before) != opened_identity
                ):
                    raise PgnSourceChangedError("PGN source changed while being opened")
                if fd_before.st_size > MAX_PGN_SOURCE_BYTES:
                    raise PgnResourceLimitError(
                        f"PGN source exceeds the {MAX_PGN_SOURCE_BYTES}-byte safety limit"
                    )
                _assert_bound_source_path(absolute, opened_identity)

                payload = handle.read(MAX_PGN_SOURCE_BYTES + 1)
                if not isinstance(payload, bytes):
                    raise PgnFileError("PGN source returned an unsupported payload")
                if len(payload) > MAX_PGN_SOURCE_BYTES:
                    raise PgnResourceLimitError("PGN source exceeds the safety limit")

                first_sha256 = hashlib.sha256(payload).hexdigest()
                verified_sha256, verified_size = _rehash_open_source(handle)
                try:
                    fd_after = os.fstat(handle.fileno())
                except (AttributeError, OSError, ValueError) as exc:
                    raise PgnSourceChangedError(
                        "PGN source identity could not be verified"
                    ) from exc
                if (
                    verified_size != len(payload)
                    or fd_after.st_size != verified_size
                    or first_sha256 != verified_sha256
                ):
                    raise PgnSourceChangedError("PGN source changed while being read")

                _assert_bound_source_path(absolute, opened_identity)
                try:
                    source = _publish_opened_fingerprint(
                        submitted,
                        absolute,
                        path_before,
                        fd_before,
                        fd_after,
                        verified_sha256,
                    )
                except (OSError, ValueError) as exc:
                    raise PgnSourceChangedError("PGN source changed while being read") from exc
                _assert_bound_source_path(absolute, opened_identity)
    except PgnFileError:
        raise
    except OSError as exc:
        raise PgnFileError("PGN source could not be read safely") from exc

    legacy_windows_1251 = False
    if isinstance(payload, str):
        text = payload
        decode_replaced = False
        if len(text.encode("utf-8", errors="replace")) > MAX_PGN_SOURCE_BYTES:
            raise PgnResourceLimitError("PGN decoded text exceeds the safety limit")
    else:
        if not isinstance(payload, bytes):
            raise PgnFileError("PGN source returned an unsupported payload")
        try:
            text = payload.decode("utf-8-sig", errors="strict")
            decode_replaced = False
        except UnicodeDecodeError:
            if _looks_like_windows_1251_pgn_bytes(payload):
                try:
                    text = payload.decode("cp1251", errors="strict")
                except UnicodeDecodeError:
                    # Windows-1251 has one undefined byte (0x98). A malformed
                    # source that merely resembles legacy Cyrillic PGN must
                    # retain the pre-fallback fail-safe behavior rather than
                    # leaking a raw codec exception from the file boundary.
                    text = payload.decode("utf-8-sig", errors="replace")
                    decode_replaced = True
                else:
                    decode_replaced = False
                    legacy_windows_1251 = True
            else:
                text = payload.decode("utf-8-sig", errors="replace")
                decode_replaced = True

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return source, text, decode_replaced, legacy_windows_1251


def _parse_file_games(text: str) -> tuple[PgnGame, ...]:
    """Prefer canonical D06 recovery normalization without narrowing inspection.

    The historical structural parser is intentionally permissive so damaged
    sources can still be inspected and classified. The canonical D06 parser
    additionally normalizes supported symbolic annotations such as ``c4?!``
    into SAN ``c4`` plus NAG ``?!`` before an editable workspace sees them.

    Use canonical recovery whenever it accepts the source. A semantic recovery
    rejection may fall back to the historical structural parser so damaged
    inspection remains available. Canonical resource-limit rejections are never
    eligible for fallback: doing so would bypass the bounded D06 input contract.
    Filesystem, decoding and publication semantics remain outside this helper.
    """

    try:
        return parse_pgn_text(text, strict=False)
    except PgnRoundTripError as exc:
        if exc.code in _RESOURCE_LIMIT_CODES:
            raise
        return tuple(parse_games(text))


def open_pgn(path: str | Path) -> PgnOpenResult:
    """Open one source-bound PGN snapshot without mutating the source."""

    source_path = Path(path)
    source, text, decode_replaced, legacy_windows_1251 = _read_text_snapshot(source_path)
    games = _parse_file_games(text)
    warnings: list[str] = []
    if decode_replaced:
        warnings.append(
            "Invalid UTF-8 bytes were replaced while reading; save to a new file before editing the source."
        )
    if legacy_windows_1251:
        warnings.append(
            "Legacy Windows-1251 PGN was decoded losslessly; use Save As so the original legacy-encoded source is not overwritten."
        )
    return PgnOpenResult(source=source, games=games, global_warnings=tuple(warnings))


def _current_sha256(path: Path) -> str | None:
    try:
        path.lstat()
    except FileNotFoundError:
        return None
    return fingerprint(path).sha256


def _create_hardlink_snapshot(destination: Path) -> Path:
    """Create a same-directory hard-link snapshot of an existing destination.

    The link keeps the pre-publication inode reachable after ``os.replace``. If
    an in-place competing writer mutates that inode in the final publication
    window, its bytes remain recoverable and the stale save can roll back rather
    than silently destroying the newer edit.
    """

    for _ in range(8):
        fd, raw_name = tempfile.mkstemp(
            dir=str(destination.parent),
            prefix=destination.name + ".cas-",
            suffix=".bak",
        )
        os.close(fd)
        snapshot = Path(raw_name)
        snapshot.unlink()
        try:
            os.link(destination, snapshot)
            return snapshot
        except FileExistsError:
            continue
        except OSError as exc:
            raise PgnFileError("PGN commit snapshot could not be created safely") from exc
    raise PgnFileError("PGN commit snapshot could not reserve a unique path")


def _cleanup_redundant_link_after_commit(path: Path) -> None:
    """Best-effort cleanup after publication has already committed.

    A hard-link publication or recovery snapshot can leave one redundant name
    after the destination has become authoritative. Cleanup failure at that
    point must never be reported as a failed save: callers would otherwise be
    told to retry an operation whose destination already contains the requested
    commit. We retry through the lower-level unlink primitive and, if the
    filesystem still refuses removal, leave the redundant link intact rather
    than falsifying commit state or deleting the committed destination.
    """

    try:
        path.unlink()
        return
    except FileNotFoundError:
        return
    except OSError:
        pass

    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    except OSError:
        # The destination is already committed. Residual cleanup is maintenance,
        # not a reason to misreport the save as failed.
        pass


def _publish_no_clobber(tmp_path: Path, destination: Path) -> None:
    """Atomically publish ``tmp_path`` only if ``destination`` is still absent."""

    try:
        os.link(tmp_path, destination)
    except FileExistsError:
        raise
    except OSError as exc:
        raise PgnFileError("PGN no-clobber publication is unavailable") from exc
    _cleanup_redundant_link_after_commit(tmp_path)


def _publish_expected_hash(
    tmp_path: Path,
    destination: Path,
    expected_sha256: str,
) -> None:
    """Publish with recoverable optimistic-CAS semantics for an existing file."""

    if _current_sha256(destination) != expected_sha256:
        raise PgnConcurrentWriteError(f"PGN changed since it was opened: {destination}")

    snapshot = _create_hardlink_snapshot(destination)
    preserve_snapshot = False
    try:
        if _current_sha256(destination) != expected_sha256:
            raise PgnConcurrentWriteError(f"PGN changed since it was opened: {destination}")
        if _current_sha256(snapshot) != expected_sha256:
            raise PgnConcurrentWriteError(f"PGN changed since it was opened: {destination}")

        os.replace(tmp_path, destination)

        # ``snapshot`` references the pre-publication inode. A competing writer
        # that modified that inode immediately before our replace changes this
        # digest too. Restore those newer bytes before reporting the conflict.
        try:
            snapshot_sha256 = _current_sha256(snapshot)
        except (OSError, ValueError, PgnFileError) as exc:
            preserve_snapshot = True
            raise PgnFileError(
                "PGN publication could not be verified safely; recovery snapshot was preserved"
            ) from exc

        if snapshot_sha256 != expected_sha256:
            try:
                os.replace(snapshot, destination)
            except OSError as exc:
                preserve_snapshot = True
                raise PgnFileError(
                    "PGN concurrent-write rollback failed; recovery snapshot was preserved"
                ) from exc
            snapshot = None
            raise PgnConcurrentWriteError(f"PGN changed during publication: {destination}")
    finally:
        if snapshot is not None and not preserve_snapshot:
            _cleanup_redundant_link_after_commit(snapshot)


def _write_games_incrementally(handle: TextIO, games: Iterable[PgnGame]) -> None:
    """Write canonical multi-game PGN without materializing the collection/text."""

    first = True
    for game in games:
        block = serialize_game(game).rstrip()
        if not first:
            handle.write("\n\n")
        handle.write(block)
        first = False
    if not first:
        handle.write("\n")


def _validated_expected_sha256(value: object) -> str | None:
    """Validate optimistic-CAS identity before any filesystem mutation."""

    if value is None:
        return None
    # Digests cross CLI/application boundaries. Require passive canonical text
    # before equality/hash work so a str subclass cannot execute provider hooks.
    if type(value) is not str:
        raise TypeError("expected_sha256 must be lowercase SHA-256 hex or None")
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("expected_sha256 must be lowercase SHA-256 hex")
    return value


def save_pgn_atomic(
    path: str | Path,
    games: Iterable[PgnGame],
    *,
    overwrite: bool = False,
    expected_sha256: str | None = None,
    pre_publish_check: Callable[[], None] | None = None,
) -> SourceFingerprint:
    """Serialize GameTree content and commit one complete PGN file safely.

    Games are consumed and serialized one at a time into the unpublished
    temporary file. This preserves canonical ``serialize_games`` byte layout
    without holding the complete collection or complete PGN text in memory.
    Publication remains atomic: iterator/serialization failure leaves the
    destination unchanged and the temporary file is removed.

    ``overwrite=False`` uses an atomic no-clobber hard-link publication in the
    destination directory. ``expected_sha256`` uses a recoverable pre-commit
    inode snapshot so an in-place writer racing at publication is detected and
    restored instead of silently lost. Plain ``overwrite=True`` without an
    expected digest intentionally requests unconditional replacement.

    ``pre_publish_check`` runs after the temporary file has been completely
    written, flushed and fsynced, but before any publication primitive can make
    it visible at ``destination``. If it raises, the temporary file is
    cleaned and the destination remains unchanged.
    """

    if type(overwrite) is not bool:
        raise TypeError("overwrite must be a boolean")
    if pre_publish_check is not None and not callable(pre_publish_check):
        raise TypeError("pre_publish_check must be callable")
    expected_sha256 = _validated_expected_sha256(expected_sha256)
    destination = Path(path)
    _reject_export_indirection(destination)
    if destination.exists() and not overwrite:
        raise FileExistsError(f"PGN already exists: {destination}")

    current_sha = _current_sha256(destination)
    if expected_sha256 is not None and current_sha != expected_sha256:
        raise PgnConcurrentWriteError(f"PGN changed since it was opened: {destination}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    _reject_export_indirection(destination)
    parent_identity = _export_parent_identity(destination.parent)

    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=str(destination.parent),
            prefix=destination.name + ".",
            suffix=".tmp",
            delete=False,
        ) as handle:
            tmp_path = Path(handle.name)
            # NamedTemporaryFile resolves the parent pathname again. Re-check
            # the exact directory object before consuming any user chess data,
            # so a direct-directory substitution cannot redirect the payload.
            _assert_bound_export_parent(destination.parent, parent_identity)
            _write_games_incrementally(handle, games)
            handle.flush()
            os.fsync(handle.fileno())

        _reject_export_indirection(destination)
        _assert_bound_export_parent(destination.parent, parent_identity)
        if pre_publish_check is not None:
            pre_publish_check()
        _reject_export_indirection(destination)
        _assert_bound_export_parent(destination.parent, parent_identity)
        if not overwrite:
            _publish_no_clobber(tmp_path, destination)
            tmp_path = None
        elif expected_sha256 is not None:
            _publish_expected_hash(tmp_path, destination, expected_sha256)
            tmp_path = None
        else:
            os.replace(tmp_path, destination)
            tmp_path = None
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass

    # Publication has crossed the commit boundary. Bind the returned
    # provenance to the same destination-directory object as the write;
    # otherwise a post-commit directory substitution could make fingerprint()
    # authenticate unrelated bytes at the same pathname and falsely report them
    # as this save. Any failure from this point is materially different from a
    # pre-publication failure: the destination may already contain the new
    # bytes, so propagate a distinct terminal truth and never invite a blind
    # retry against stale in-memory provenance.
    try:
        _assert_bound_export_parent(destination.parent, parent_identity)
        published = fingerprint(destination)
        _assert_bound_export_parent(destination.parent, parent_identity)
    except Exception as exc:
        raise PgnPublicationUnverifiedError(
            "PGN publication completed but final destination provenance could not be verified"
        ) from exc
    return published


def export_game_atomic(
    path: str | Path,
    game: PgnGame,
    *,
    overwrite: bool = False,
    expected_sha256: str | None = None,
) -> SourceFingerprint:
    """Convenience wrapper for exporting one game with the same safety rules."""

    return save_pgn_atomic(path, (game,), overwrite=overwrite, expected_sha256=expected_sha256)
