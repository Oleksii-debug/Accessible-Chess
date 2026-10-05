from __future__ import annotations

"""Detached PGN save snapshots for owner-thread/worker-thread composition.

This module is deliberately a narrow companion to :mod:`acs.pgn_document`.
It does not parse PGN, serialize PGN, own chess rules, or implement a second
filesystem publication path.  A live ``PgnDocumentSession`` is sampled only on
the owner thread; a detached game tuple is then safe to hand to a worker, which
publishes through the existing ``save_pgn_atomic`` authority.  The resulting
source fingerprint is committed back to the same live session on the owner
thread.

The commit step intentionally records the digest that was actually published,
not whatever content happens to be current when the worker finishes.  Edits
made while a save is running therefore remain dirty while the source
fingerprint still advances to the newly published generation.  This is the
lower-level transaction needed by a non-blocking Windows Save/Save As host.
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from weakref import ReferenceType, ref

from .gametree import PgnGame
from .import_contract import SourceFingerprint, SourceReadCancelledError, fingerprint
from .pgn_document import (
    PgnDocumentError,
    PgnDocumentErrorCode,
    PgnDocumentSession,
    PgnDocumentView,
)
from .pgn_service import (
    PgnPublicationUnverifiedError,
    _same_direct_path,
    _validated_expected_sha256,
    save_pgn_atomic,
)
from .pgn_workspace import PgnWorkspace, PgnWorkspaceError


_PLATFORM_PATH_TYPE = type(Path())


def _passive_platform_path(value: object, *, field_name: str) -> Path:
    """Accept only inert built-in text or the exact platform Path implementation."""

    if type(value) is str:
        return Path(value)
    if type(value) is _PLATFORM_PATH_TYPE:
        return value
    raise TypeError(f"{field_name} must be plain text or an exact platform Path")


class PgnSaveMode(str, Enum):
    SAVE = "save"
    SAVE_AS = "save_as"


class PgnSaveCancelledError(RuntimeError):
    """Raised only while cancellation can still prevent durable publication."""


@dataclass(frozen=True, slots=True)
class _PgnSaveSnapshotBinding:
    """Owner-thread proof of the exact controls/provenance captured for one save."""

    mode: PgnSaveMode
    document_revision: int
    content_digest: str
    source_before: SourceFingerprint | None
    source_overwrite_safe_before: bool
    saved_digest_before: str | None
    global_warnings_before: tuple[str, ...]
    workspace_ref: ReferenceType[PgnWorkspace]
    session_ref: ReferenceType[PgnDocumentSession]


@dataclass(frozen=True, slots=True)
class PgnSaveSnapshot:
    """Detached, exact document generation prepared for background publication."""

    mode: PgnSaveMode
    document_revision: int
    content_digest: str
    games: tuple[PgnGame, ...]
    source_before: SourceFingerprint | None
    source_overwrite_safe_before: bool
    _saved_digest_before: str | None = field(repr=False)
    _global_warnings_before: tuple[str, ...] = field(repr=False, compare=False)
    _workspace_ref: ReferenceType[PgnWorkspace] = field(repr=False, compare=False)
    _session_ref: ReferenceType[PgnDocumentSession] = field(repr=False, compare=False)
    _capture_binding: _PgnSaveSnapshotBinding = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class _PassiveSnapshotMetadata:
    mode: PgnSaveMode
    document_revision: int
    content_digest: str
    games: tuple[PgnGame, ...]
    source_before: SourceFingerprint | None
    source_overwrite_safe_before: bool
    saved_digest_before: str | None
    global_warnings_before: tuple[str, ...]
    workspace_ref: ReferenceType[PgnWorkspace]
    session_ref: ReferenceType[PgnDocumentSession]


@dataclass(frozen=True, slots=True)
class _PgnSavePublicationBinding:
    """Private worker proof tying durable bytes to one captured session generation."""

    snapshot: PgnSaveSnapshot
    mode: PgnSaveMode
    document_revision: int
    content_digest: str
    source_before: SourceFingerprint | None
    source_overwrite_safe_before: bool
    saved_digest_before: str | None
    global_warnings_before: tuple[str, ...]
    workspace_ref: ReferenceType[PgnWorkspace]
    session_ref: ReferenceType[PgnDocumentSession]
    saved: SourceFingerprint


@dataclass(frozen=True, slots=True)
class PgnSavePublication:
    """Canonical file publication result bound to the snapshot that produced it."""

    snapshot: PgnSaveSnapshot
    saved: SourceFingerprint
    _binding: _PgnSavePublicationBinding = field(repr=False, compare=False)


def _stale(message: str) -> PgnDocumentError:
    return PgnDocumentError(message, code=PgnDocumentErrorCode.CONTEXT_STALE)


def _detached_source_fingerprint(
    source: object,
    *,
    allow_none: bool = False,
) -> SourceFingerprint | None:
    """Copy provenance scalars once so caller-owned frozen DTOs cannot alias state."""

    if source is None:
        if allow_none:
            return None
        raise TypeError("PGN save provenance fingerprint is required")
    if type(source) is not SourceFingerprint:
        raise TypeError("PGN save provenance fingerprint is invalid")
    path = source.path
    size = source.size
    sha256 = source.sha256
    suffix = source.suffix
    if (
        type(path) is not str
        or type(size) is not int
        or type(sha256) is not str
        or type(suffix) is not str
    ):
        raise TypeError("PGN save provenance fields must be passive built-in scalars")
    if not path:
        raise ValueError("PGN save provenance path must not be empty")
    if size < 0:
        raise ValueError("PGN save provenance size must not be negative")
    if (
        len(sha256) != 64
        or any(character not in "0123456789abcdef" for character in sha256)
    ):
        raise ValueError("PGN save provenance digest must be lowercase SHA-256 hex")
    canonical_suffix = Path(path).suffix.lower()
    if suffix != suffix.lower() or suffix != canonical_suffix:
        raise ValueError("PGN save provenance suffix does not match its source path")
    return SourceFingerprint(
        path=path,
        size=size,
        sha256=sha256,
        suffix=suffix,
    )


def _passive_snapshot_metadata(snapshot: object) -> _PassiveSnapshotMetadata:
    """Detach passive snapshot metadata before worker/owner boundary use."""

    if type(snapshot) is not PgnSaveSnapshot:
        raise TypeError("PGN save snapshot is malformed")
    mode = snapshot.mode
    document_revision = snapshot.document_revision
    content_digest = snapshot.content_digest
    games = snapshot.games
    source_before = snapshot.source_before
    source_overwrite_safe_before = snapshot.source_overwrite_safe_before
    saved_digest_before = snapshot._saved_digest_before
    global_warnings_before = snapshot._global_warnings_before
    workspace_ref = snapshot._workspace_ref
    session_ref = snapshot._session_ref
    capture_binding = snapshot._capture_binding

    if type(mode) is not PgnSaveMode:
        raise TypeError("PGN save snapshot mode is invalid")
    if type(document_revision) is not int or document_revision < 0:
        raise TypeError("PGN save snapshot revision is invalid")
    if (
        type(content_digest) is not str
        or len(content_digest) != 64
        or any(character not in "0123456789abcdef" for character in content_digest)
    ):
        raise TypeError("PGN save snapshot digest is invalid")
    if type(games) is not tuple:
        raise TypeError("PGN save snapshot games must be a built-in tuple")
    if type(source_overwrite_safe_before) is not bool:
        raise TypeError("PGN save snapshot source safety flag is invalid")
    if saved_digest_before is not None and (
        type(saved_digest_before) is not str
        or len(saved_digest_before) != 64
        or any(character not in "0123456789abcdef" for character in saved_digest_before)
    ):
        raise TypeError("PGN save snapshot saved digest is invalid")
    if type(global_warnings_before) is not tuple or any(
        type(item) is not str for item in global_warnings_before
    ):
        raise TypeError("PGN save snapshot global warnings are invalid")
    if type(workspace_ref) is not ReferenceType:
        raise TypeError("PGN save snapshot workspace reference is invalid")
    if type(session_ref) is not ReferenceType:
        raise TypeError("PGN save snapshot session reference is invalid")
    if type(capture_binding) is not _PgnSaveSnapshotBinding:
        raise TypeError("PGN save snapshot capture binding is invalid")

    detached_source = _detached_source_fingerprint(
        source_before,
        allow_none=True,
    )
    bound_source = _detached_source_fingerprint(
        capture_binding.source_before,
        allow_none=True,
    )
    if (
        type(capture_binding.mode) is not PgnSaveMode
        or type(capture_binding.document_revision) is not int
        or capture_binding.document_revision < 0
        or type(capture_binding.content_digest) is not str
        or len(capture_binding.content_digest) != 64
        or any(
            character not in "0123456789abcdef"
            for character in capture_binding.content_digest
        )
        or type(capture_binding.source_overwrite_safe_before) is not bool
        or (
            capture_binding.saved_digest_before is not None
            and (
                type(capture_binding.saved_digest_before) is not str
                or len(capture_binding.saved_digest_before) != 64
                or any(
                    character not in "0123456789abcdef"
                    for character in capture_binding.saved_digest_before
                )
            )
        )
        or type(capture_binding.global_warnings_before) is not tuple
        or any(
            type(item) is not str
            for item in capture_binding.global_warnings_before
        )
        or type(capture_binding.workspace_ref) is not ReferenceType
        or type(capture_binding.session_ref) is not ReferenceType
    ):
        raise TypeError("PGN save snapshot capture binding metadata is invalid")
    if (
        mode is not capture_binding.mode
        or document_revision != capture_binding.document_revision
        or content_digest != capture_binding.content_digest
        or detached_source != bound_source
        or source_overwrite_safe_before
        is not capture_binding.source_overwrite_safe_before
        or saved_digest_before != capture_binding.saved_digest_before
        or global_warnings_before != capture_binding.global_warnings_before
        or workspace_ref is not capture_binding.workspace_ref
        or session_ref is not capture_binding.session_ref
    ):
        raise _stale("PGN save snapshot metadata changed after capture")

    return _PassiveSnapshotMetadata(
        mode=mode,
        document_revision=document_revision,
        content_digest=content_digest,
        games=games,
        source_before=detached_source,
        source_overwrite_safe_before=source_overwrite_safe_before,
        saved_digest_before=saved_digest_before,
        global_warnings_before=global_warnings_before,
        workspace_ref=workspace_ref,
        session_ref=session_ref,
    )


def _require_session(session: object) -> PgnDocumentSession:
    # This is an authority boundary. Executable subclasses must not be able to
    # redefine session or workspace behavior while a supposedly detached
    # snapshot is being created or committed. Current Product still permits a
    # PgnWorkspace subclass at the document constructor, so enforce the exact
    # canonical workspace here as well until/after that ingress is converged.
    if type(session) is not PgnDocumentSession:
        raise TypeError("PGN save snapshot requires an exact PgnDocumentSession")
    if type(session.workspace) is not PgnWorkspace:
        raise TypeError("PGN save snapshot requires an exact PgnWorkspace")
    return session


def _canonical_detached_games(
    games: tuple[PgnGame, ...],
    *,
    expected_digest: str | None = None,
) -> tuple[tuple[PgnGame, ...], str]:
    """Revalidate and re-detach a mutable DTO graph at a thread boundary."""

    try:
        workspace = PgnWorkspace(games)
        digest = workspace.content_digest
        detached = workspace.games()
    except (PgnWorkspaceError, TypeError, ValueError) as exc:
        raise _stale("PGN save snapshot is no longer canonical") from exc
    if expected_digest is not None and digest != expected_digest:
        raise _stale("PGN save snapshot content changed before publication")
    return detached, digest


def _validated_cancel_check(
    cancel_check: Callable[[], bool] | None,
) -> Callable[[], bool] | None:
    if cancel_check is not None and not callable(cancel_check):
        raise TypeError("cancel_check must be callable or None")
    return cancel_check


def _raise_if_cancelled(cancel_check: Callable[[], bool] | None) -> None:
    if cancel_check is None:
        return
    cancelled = cancel_check()
    if type(cancelled) is not bool:
        raise TypeError("cancel_check must return a boolean")
    if cancelled:
        raise PgnSaveCancelledError("PGN save cancelled before publication")


def _cancellable_games(
    games: tuple[PgnGame, ...],
    cancel_check: Callable[[], bool] | None,
) -> Iterator[PgnGame]:
    for game in games:
        # save_pgn_atomic serializes games incrementally. Poll between canonical
        # game records so a multi-game save can abort without publication while
        # preserving the writer's existing temp-file cleanup semantics.
        _raise_if_cancelled(cancel_check)
        yield game


def capture_pgn_save_snapshot(
    session: PgnDocumentSession,
    *,
    mode: PgnSaveMode,
) -> PgnSaveSnapshot:
    """Freeze one exact live document generation without filesystem publication.

    Call this from the application owner thread.  The returned games are the
    detached copies supplied by ``PgnWorkspace.games()``; no live workspace is
    handed to the worker.
    """

    current = _require_session(session)
    if type(mode) is not PgnSaveMode:
        raise TypeError("PGN save mode is invalid")

    source = _detached_source_fingerprint(current.source, allow_none=True)
    workspace = current.workspace
    document_revision = current.document_revision
    workspace_revision = workspace.content_revision
    source_overwrite_safe = current._source_overwrite_safe
    saved_digest = current._saved_digest
    global_warnings = current._global_warnings
    if type(workspace_revision) is not int or workspace_revision < 0:
        raise TypeError("PGN save workspace revision is invalid")
    if type(source_overwrite_safe) is not bool:
        raise TypeError("PGN save source safety flag is invalid")
    if saved_digest is not None and (
        type(saved_digest) is not str
        or len(saved_digest) != 64
        or any(character not in "0123456789abcdef" for character in saved_digest)
    ):
        raise TypeError("PGN save saved digest is invalid")
    if type(global_warnings) is not tuple or any(
        type(item) is not str for item in global_warnings
    ):
        raise TypeError("PGN save global warnings are invalid")

    if mode is PgnSaveMode.SAVE:
        if source is None:
            raise PgnDocumentError(
                "document has no source; use Save As",
                code=PgnDocumentErrorCode.NO_SOURCE,
            )
        if not source_overwrite_safe:
            raise PgnDocumentError(
                "source required recovery; use Save As to preserve the original",
                code=PgnDocumentErrorCode.SOURCE_REQUIRES_SAVE_AS,
            )

    # The exact canonical workspace is already the content authority. Freeze its
    # detached games once and bind them to the digest established by the
    # workspace's last strict validation. Do not strict-round-trip the detached
    # graph here: capture executes on the Windows owner thread. The worker
    # revalidates this detached graph against the bound digest immediately
    # before publication, so malformed/tampered snapshots still fail closed.
    games = workspace.games()
    detached_digest = workspace.content_digest
    workspace_revision_after = workspace.content_revision
    source_after = _detached_source_fingerprint(current.source, allow_none=True)
    source_overwrite_safe_after = current._source_overwrite_safe
    saved_digest_after = current._saved_digest
    global_warnings_after = current._global_warnings
    if (
        type(detached_digest) is not str
        or len(detached_digest) != 64
        or any(character not in "0123456789abcdef" for character in detached_digest)
    ):
        raise TypeError("PGN save workspace digest is invalid")
    if (
        type(workspace_revision_after) is not int
        or workspace_revision_after < 0
    ):
        raise TypeError("PGN save workspace revision is invalid")
    if type(source_overwrite_safe_after) is not bool:
        raise TypeError("PGN save source safety flag is invalid")
    if saved_digest_after is not None and (
        type(saved_digest_after) is not str
        or len(saved_digest_after) != 64
        or any(
            character not in "0123456789abcdef"
            for character in saved_digest_after
        )
    ):
        raise TypeError("PGN save saved digest is invalid")
    if type(global_warnings_after) is not tuple or any(
        type(item) is not str for item in global_warnings_after
    ):
        raise TypeError("PGN save global warnings are invalid")
    if (
        current.workspace is not workspace
        or current.document_revision != document_revision
        or workspace_revision_after != workspace_revision
        or source_after != source
        or source_overwrite_safe_after is not source_overwrite_safe
        or saved_digest_after != saved_digest
        or global_warnings_after != global_warnings
    ):
        raise _stale("PGN document state changed while the save snapshot was being captured")

    workspace_ref = ref(workspace)
    session_ref = ref(current)
    capture_binding = _PgnSaveSnapshotBinding(
        mode=mode,
        document_revision=document_revision,
        content_digest=detached_digest,
        source_before=_detached_source_fingerprint(source, allow_none=True),
        source_overwrite_safe_before=source_overwrite_safe,
        saved_digest_before=saved_digest,
        global_warnings_before=global_warnings,
        workspace_ref=workspace_ref,
        session_ref=session_ref,
    )
    return PgnSaveSnapshot(
        mode=mode,
        document_revision=document_revision,
        content_digest=detached_digest,
        games=games,
        source_before=source,
        source_overwrite_safe_before=source_overwrite_safe,
        _saved_digest_before=saved_digest,
        _global_warnings_before=global_warnings,
        _workspace_ref=workspace_ref,
        _session_ref=session_ref,
        _capture_binding=capture_binding,
    )


def expected_pgn_destination_sha256(
    path: str | Path,
    *,
    cancel_check: Callable[[], bool] | None = None,
) -> str | None:
    """Fingerprint an existing destination for explicit Save-As replacement.

    This function is intended for the same worker that performs publication,
    keeping potentially expensive destination hashing away from the Windows UI
    thread. The canonical fingerprint authority polls cancellation between its
    finite hash chunks on both verification passes, so a large/slow destination
    does not make Cancel wait for the complete two-pass digest.
    """

    check = _validated_cancel_check(cancel_check)
    _raise_if_cancelled(check)
    destination = _passive_platform_path(
        path,
        field_name="PGN save destination",
    )
    if not destination.exists():
        return None
    try:
        fingerprinted = fingerprint(destination, cancel_check=check)
    except SourceReadCancelledError as exc:
        raise PgnSaveCancelledError(
            "PGN save cancelled during destination fingerprinting"
        ) from exc
    detached = _detached_source_fingerprint(fingerprinted)
    assert detached is not None
    if not _same_direct_path(destination, detached.path):
        raise ValueError("PGN destination fingerprint does not match the requested path")
    _raise_if_cancelled(check)
    return detached.sha256


def publish_pgn_save_snapshot(
    snapshot: PgnSaveSnapshot,
    *,
    path: str | Path | None = None,
    overwrite: bool = False,
    expected_sha256: str | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> PgnSavePublication:
    """Publish a detached snapshot through the existing canonical PGN writer.

    This function never reads or mutates the live session.  It is therefore the
    worker-thread half of the transaction.  Snapshot DTOs are mutable, so the
    worker first makes one private canonical copy after digest validation; a
    caller retaining the public snapshot cannot race-mutate the graph consumed
    by the canonical writer after that validation point.

    Save As treats ``overwrite=True`` as an explicit compare-and-swap replacement
    request and therefore always requires ``expected_sha256`` before writer I/O.
    A new destination must use ``overwrite=False`` so the canonical writer owns
    the no-clobber create race instead of relying on a prior existence check.

    Cancellation is polled before filesystem work, between serialized games,
    and through ``save_pgn_atomic(pre_publish_check=...)`` after flush/fsync but
    before the atomic publication primitive.  There is deliberately no cancel
    poll after ``save_pgn_atomic`` returns: at that point durable publication won
    and the caller must report/commit success rather than contradictory cancel.
    """

    metadata = _passive_snapshot_metadata(snapshot)
    if type(overwrite) is not bool:
        raise TypeError("overwrite must be a boolean")
    check = _validated_cancel_check(cancel_check)
    _raise_if_cancelled(check)
    publication_games, _digest = _canonical_detached_games(
        metadata.games,
        expected_digest=metadata.content_digest,
    )
    _raise_if_cancelled(check)

    writer_games = _cancellable_games(publication_games, check)
    pre_publish_check = None if check is None else lambda: _raise_if_cancelled(check)

    if metadata.mode is PgnSaveMode.SAVE:
        if path is not None or overwrite or expected_sha256 is not None:
            raise ValueError("Save snapshot destination is bound to its source")
        source = _detached_source_fingerprint(
            metadata.source_before,
            allow_none=True,
        )
        if source is None:
            raise _stale("Save snapshot lost its source binding")
        if not metadata.source_overwrite_safe_before:
            raise PgnDocumentError(
                "source required recovery; use Save As to preserve the original",
                code=PgnDocumentErrorCode.SOURCE_REQUIRES_SAVE_AS,
            )
        publication_destination: str | Path = source.path
        saved = save_pgn_atomic(
            source.path,
            writer_games,
            overwrite=True,
            expected_sha256=source.sha256,
            pre_publish_check=pre_publish_check,
        )
    elif metadata.mode is PgnSaveMode.SAVE_AS:
        if path is None:
            raise TypeError("Save As snapshot requires a destination path")
        destination = _passive_platform_path(
            path,
            field_name="PGN Save As destination",
        )
        expected_sha256 = _validated_expected_sha256(expected_sha256)
        if overwrite and expected_sha256 is None:
            raise PgnDocumentError(
                "Save As overwrite requires its expected destination fingerprint",
                code=PgnDocumentErrorCode.DESTINATION_VERSION_REQUIRED,
            )
        source = _detached_source_fingerprint(
            metadata.source_before,
            allow_none=True,
        )
        if (
            source is not None
            and not metadata.source_overwrite_safe_before
            and _same_direct_path(destination, source.path)
        ):
            raise PgnDocumentError(
                "recovery source must be preserved; choose a different Save As destination",
                code=(
                    PgnDocumentErrorCode.RECOVERY_SOURCE_REQUIRES_DIFFERENT_DESTINATION
                ),
            )
        # If Save As points back to the captured source, a worker-time target
        # fingerprint may describe a newer external edit. Preserve the captured
        # source CAS generation instead of adopting that edit as write authority.
        if (
            overwrite
            and source is not None
            and _same_direct_path(destination, source.path)
        ):
            expected_sha256 = source.sha256
        publication_destination = destination
        saved = save_pgn_atomic(
            destination,
            writer_games,
            overwrite=overwrite,
            expected_sha256=expected_sha256,
            pre_publish_check=pre_publish_check,
        )
    else:  # pragma: no cover - exact enum construction makes this defensive only.
        raise TypeError("PGN save mode is invalid")

    bound_saved = _detached_source_fingerprint(saved)
    assert bound_saved is not None
    if not _same_direct_path(publication_destination, bound_saved.path):
        raise PgnPublicationUnverifiedError(
            "PGN writer returned provenance for a different publication path"
        )
    binding = _PgnSavePublicationBinding(
        snapshot=snapshot,
        mode=metadata.mode,
        document_revision=metadata.document_revision,
        content_digest=metadata.content_digest,
        source_before=_detached_source_fingerprint(
            metadata.source_before,
            allow_none=True,
        ),
        source_overwrite_safe_before=metadata.source_overwrite_safe_before,
        saved_digest_before=metadata.saved_digest_before,
        global_warnings_before=metadata.global_warnings_before,
        workspace_ref=metadata.workspace_ref,
        session_ref=metadata.session_ref,
        saved=bound_saved,
    )
    return PgnSavePublication(snapshot=snapshot, saved=saved, _binding=binding)


def commit_pgn_save_publication(
    session: PgnDocumentSession,
    publication: PgnSavePublication,
):
    """Commit a worker publication to the same live session on its owner thread.

    Newer in-memory edits are retained and remain dirty.  A source/provenance
    change from another save makes this completion stale and it is rejected.
    Replaying the exact already-committed publication is idempotent.
    """

    current = _require_session(session)
    if type(publication) is not PgnSavePublication:
        raise TypeError("PGN save commit requires an exact publication")
    binding = publication._binding
    if type(binding) is not _PgnSavePublicationBinding:
        raise TypeError("PGN save publication binding is malformed")
    if publication.snapshot is not binding.snapshot:
        raise _stale("PGN save publication snapshot binding changed after publication")

    snapshot = publication.snapshot
    metadata = _passive_snapshot_metadata(snapshot)
    bound_source = _detached_source_fingerprint(
        binding.source_before,
        allow_none=True,
    )
    bound_saved = _detached_source_fingerprint(binding.saved)
    assert bound_saved is not None
    if (
        type(binding.mode) is not PgnSaveMode
        or type(binding.document_revision) is not int
        or binding.document_revision < 0
        or type(binding.content_digest) is not str
        or len(binding.content_digest) != 64
        or any(character not in "0123456789abcdef" for character in binding.content_digest)
        or type(binding.source_overwrite_safe_before) is not bool
        or (
            binding.saved_digest_before is not None
            and (
                type(binding.saved_digest_before) is not str
                or len(binding.saved_digest_before) != 64
                or any(
                    character not in "0123456789abcdef"
                    for character in binding.saved_digest_before
                )
            )
        )
        or type(binding.global_warnings_before) is not tuple
        or any(type(item) is not str for item in binding.global_warnings_before)
        or type(binding.workspace_ref) is not ReferenceType
        or type(binding.session_ref) is not ReferenceType
    ):
        raise TypeError("PGN save publication binding metadata is malformed")
    if (
        metadata.mode is not binding.mode
        or metadata.document_revision != binding.document_revision
        or metadata.content_digest != binding.content_digest
        or metadata.source_before != bound_source
        or metadata.source_overwrite_safe_before
        is not binding.source_overwrite_safe_before
        or metadata.saved_digest_before != binding.saved_digest_before
        or metadata.global_warnings_before != binding.global_warnings_before
        or metadata.workspace_ref is not binding.workspace_ref
        or metadata.session_ref is not binding.session_ref
    ):
        raise _stale("PGN save snapshot metadata changed after publication")

    raw_saved = publication.saved
    saved = _detached_source_fingerprint(raw_saved)
    assert saved is not None
    if saved != bound_saved:
        raise _stale("PGN save publication provenance changed after publication")

    source_before = bound_source
    if binding.session_ref() is not current:
        raise _stale("PGN save publication belongs to a different document session")
    live_workspace = current.workspace
    if binding.workspace_ref() is not live_workspace:
        raise _stale("PGN workspace changed before the save publication could commit")

    # Re-read live provenance only through passive exact-scalar validation
    # before any equality work. Frozen SourceFingerprint instances and the
    # session's saved digest can still be corrupted through low-level object
    # mutation while a worker is publishing; comparing such active subclass
    # values here would execute caller code on the owner/UI thread after durable
    # publication. Fail closed instead so the host can report commit failure
    # without rebinding in-memory provenance.
    live_source = _detached_source_fingerprint(current.source, allow_none=True)
    live_source_overwrite_safe = current._source_overwrite_safe
    if type(live_source_overwrite_safe) is not bool:
        raise TypeError("PGN live source safety flag is invalid")
    live_saved_digest = current._saved_digest
    live_global_warnings = current._global_warnings
    if live_saved_digest is not None and (
        type(live_saved_digest) is not str
        or len(live_saved_digest) != 64
        or any(
            character not in "0123456789abcdef"
            for character in live_saved_digest
        )
    ):
        raise TypeError("PGN live saved digest is invalid")
    if type(live_global_warnings) is not tuple or any(
        type(item) is not str for item in live_global_warnings
    ):
        raise TypeError("PGN live global warnings are invalid")
    live_content_digest = live_workspace.content_digest
    if (
        type(live_content_digest) is not str
        or len(live_content_digest) != 64
        or any(
            character not in "0123456789abcdef"
            for character in live_content_digest
        )
    ):
        raise TypeError("PGN live workspace digest is invalid")
    live_document_revision = current.document_revision
    if type(live_document_revision) is not int or live_document_revision < 0:
        raise TypeError("PGN live document revision is invalid")

    # Exact replay after a successful owner-thread commit is harmless.  This is
    # checked before source-staleness because an unchanged Save can legitimately
    # produce the same fingerprint as its source generation.
    if live_source == saved and live_saved_digest == binding.content_digest:
        return current.view()

    # Ordinary edits do not mutate either source provenance or the saved
    # baseline.  A competing successful Save/Save As does.  Bind both values so
    # an older worker cannot later overwrite newer publication authority even if
    # a path happens to cycle back to the same source.
    if (
        live_source != source_before
        or live_saved_digest != binding.saved_digest_before
        or live_source_overwrite_safe
        is not binding.source_overwrite_safe_before
        or live_global_warnings != binding.global_warnings_before
    ):
        raise _stale("PGN source changed before the save publication could commit")

    if binding.mode is PgnSaveMode.SAVE:
        source = source_before
        if source is None or Path(saved.path).absolute() != Path(source.path).absolute():
            raise _stale("Save publication does not match the captured source")
    elif binding.mode is not PgnSaveMode.SAVE_AS:
        raise TypeError("PGN save mode is invalid")

    # Validate the complete owner-thread presentation before mutating either
    # the workspace persistence checkpoint or session provenance.  The file is
    # already durable at this point, so any malformed cursor/warning/presentation
    # state must become SAVE_COMMIT_FAILED without leaving an in-memory half
    # commit.  This view was historically materialized only after the mutations,
    # which could report failure after source/saved/revision had already advanced.
    try:
        precommit_view = current.view()
        if (
            type(precommit_view) is not PgnDocumentView
            or type(precommit_view.game_count) is not int
            or precommit_view.game_count < 1
            or type(precommit_view.selected_game_index) is not int
            or precommit_view.selected_game_index < 0
            or precommit_view.selected_game_index >= precommit_view.game_count
            or type(precommit_view.dirty) is not bool
            or type(precommit_view.document_revision) is not int
            or precommit_view.document_revision != live_document_revision
            or type(precommit_view.source_overwrite_safe) is not bool
            or precommit_view.source_overwrite_safe is not live_source_overwrite_safe
            or type(precommit_view.global_warnings) is not tuple
            or any(type(item) is not str for item in precommit_view.global_warnings)
        ):
            raise TypeError("PGN pre-commit presentation is invalid")
    except BaseException as exc:
        raise PgnDocumentError(
            "PGN file was written but the document checkpoint could not be finalized",
            code=PgnDocumentErrorCode.SAVE_COMMIT_FAILED,
        ) from exc

    next_source = SourceFingerprint(
        path=saved.path,
        size=saved.size,
        sha256=saved.sha256,
        suffix=saved.suffix,
    )
    next_revision = live_document_revision + 1
    final_dirty = live_content_digest != binding.content_digest
    final_view = PgnDocumentView(
        source_path=next_source.path,
        source_sha256=next_source.sha256,
        game_count=precommit_view.game_count,
        selected_game_index=precommit_view.selected_game_index,
        cursor=precommit_view.cursor,
        dirty=final_dirty,
        document_revision=next_revision,
        source_overwrite_safe=(
            True
            if binding.mode is PgnSaveMode.SAVE_AS
            else precommit_view.source_overwrite_safe
        ),
        global_warnings=(
            ()
            if binding.mode is PgnSaveMode.SAVE_AS
            else precommit_view.global_warnings
        ),
    )

    # Complete the fallible workspace checkpoint before provenance mutation.
    # No presentation reconstruction is allowed after the mutations below: the
    # already-prepared final view is returned directly, so a successful
    # checkpoint has no later fallible step that can turn into a contradictory
    # failure after in-memory provenance advances.
    try:
        if live_content_digest == binding.content_digest:
            live_workspace.mark_saved()
        else:
            # The durable worker generation is now the real persistence
            # baseline even though newer in-memory edits must remain dirty.
            # Keep workspace-level dirty tracking aligned with the session's
            # saved digest so returning exactly to the published generation
            # becomes clean in both authorities.
            live_workspace._rebase_saved_digest(binding.content_digest)
    except BaseException as exc:
        raise PgnDocumentError(
            "PGN file was written but the document checkpoint could not be finalized",
            code=PgnDocumentErrorCode.SAVE_COMMIT_FAILED,
        ) from exc

    # PgnDocumentSession owns these fields. This companion module is the only
    # background-save friend boundary: provenance advances only after the
    # canonical writer returned verified bytes and every fallible owner-thread
    # preparation step completed successfully.
    current._source = next_source
    if binding.mode is PgnSaveMode.SAVE_AS:
        current._source_overwrite_safe = True
        current._global_warnings = ()
    current._saved_digest = binding.content_digest
    current._document_revision = next_revision
    return final_view


__all__ = [
    "PgnSaveCancelledError",
    "PgnSaveMode",
    "PgnSavePublication",
    "PgnSaveSnapshot",
    "capture_pgn_save_snapshot",
    "commit_pgn_save_publication",
    "expected_pgn_destination_sha256",
    "publish_pgn_save_snapshot",
]
