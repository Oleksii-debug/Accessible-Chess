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
from .import_contract import SourceFingerprint, fingerprint
from .pgn_document import PgnDocumentError, PgnDocumentErrorCode, PgnDocumentSession
from .pgn_service import save_pgn_atomic
from .pgn_workspace import PgnWorkspace, PgnWorkspaceError


class PgnSaveMode(str, Enum):
    SAVE = "save"
    SAVE_AS = "save_as"


class PgnSaveCancelledError(RuntimeError):
    """Raised only while cancellation can still prevent durable publication."""


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
    _session_ref: ReferenceType[PgnDocumentSession] = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class PgnSavePublication:
    """Canonical file publication result bound to the snapshot that produced it."""

    snapshot: PgnSaveSnapshot
    saved: SourceFingerprint


def _stale(message: str) -> PgnDocumentError:
    return PgnDocumentError(message, code=PgnDocumentErrorCode.CONTEXT_STALE)


def _require_session(session: object) -> PgnDocumentSession:
    # This is an authority boundary.  Executable subclasses must not be able to
    # redefine workspace/source access while a supposedly detached snapshot is
    # being created or committed.
    if type(session) is not PgnDocumentSession:
        raise TypeError("PGN save snapshot requires an exact PgnDocumentSession")
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
    if not isinstance(mode, PgnSaveMode):
        raise TypeError("PGN save mode is invalid")

    source = current.source
    view = current.view()
    if mode is PgnSaveMode.SAVE:
        if source is None:
            raise PgnDocumentError(
                "document has no source; use Save As",
                code=PgnDocumentErrorCode.NO_SOURCE,
            )
        if not view.source_overwrite_safe:
            raise PgnDocumentError(
                "source required recovery; use Save As to preserve the original",
                code=PgnDocumentErrorCode.SOURCE_REQUIRES_SAVE_AS,
            )

    before_digest = current.workspace.content_digest
    games = current.workspace.games()
    canonical_games, detached_digest = _canonical_detached_games(games)
    after_digest = current.workspace.content_digest
    if before_digest != after_digest or detached_digest != before_digest:
        raise _stale("PGN content changed while the save snapshot was being captured")

    return PgnSaveSnapshot(
        mode=mode,
        document_revision=current.document_revision,
        content_digest=detached_digest,
        games=canonical_games,
        source_before=source,
        source_overwrite_safe_before=view.source_overwrite_safe,
        _saved_digest_before=current._saved_digest,
        _session_ref=ref(current),
    )


def expected_pgn_destination_sha256(
    path: str | Path,
    *,
    cancel_check: Callable[[], bool] | None = None,
) -> str | None:
    """Fingerprint an existing destination for explicit Save-As replacement.

    This function is intended for the same worker that performs publication,
    keeping potentially expensive destination hashing away from the Windows UI
    thread.  Cancellation is checked before and after hashing.  A request that
    arrives during the hash therefore still prevents later publication without
    inventing a second fingerprinting implementation.
    """

    check = _validated_cancel_check(cancel_check)
    _raise_if_cancelled(check)
    destination = Path(path)
    if not destination.exists():
        return None
    digest = fingerprint(destination).sha256
    _raise_if_cancelled(check)
    return digest


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

    Cancellation is polled before filesystem work, between serialized games,
    and through ``save_pgn_atomic(pre_publish_check=...)`` after flush/fsync but
    before the atomic publication primitive.  There is deliberately no cancel
    poll after ``save_pgn_atomic`` returns: at that point durable publication won
    and the caller must report/commit success rather than contradictory cancel.
    """

    if type(snapshot) is not PgnSaveSnapshot:
        raise TypeError("PGN save publication requires an exact snapshot")
    check = _validated_cancel_check(cancel_check)
    _raise_if_cancelled(check)
    publication_games, _digest = _canonical_detached_games(
        snapshot.games,
        expected_digest=snapshot.content_digest,
    )
    _raise_if_cancelled(check)

    writer_games = _cancellable_games(publication_games, check)
    pre_publish_check = None if check is None else lambda: _raise_if_cancelled(check)

    if snapshot.mode is PgnSaveMode.SAVE:
        if path is not None or overwrite or expected_sha256 is not None:
            raise ValueError("Save snapshot destination is bound to its source")
        source = snapshot.source_before
        if source is None:
            raise _stale("Save snapshot lost its source binding")
        if not snapshot.source_overwrite_safe_before:
            raise PgnDocumentError(
                "source required recovery; use Save As to preserve the original",
                code=PgnDocumentErrorCode.SOURCE_REQUIRES_SAVE_AS,
            )
        saved = save_pgn_atomic(
            source.path,
            writer_games,
            overwrite=True,
            expected_sha256=source.sha256,
            pre_publish_check=pre_publish_check,
        )
    elif snapshot.mode is PgnSaveMode.SAVE_AS:
        if path is None:
            raise TypeError("Save As snapshot requires a destination path")
        destination = Path(path)
        if destination.exists() and overwrite and expected_sha256 is None:
            raise PgnDocumentError(
                "existing destination requires its expected fingerprint before overwrite",
                code=PgnDocumentErrorCode.DESTINATION_VERSION_REQUIRED,
            )
        saved = save_pgn_atomic(
            destination,
            writer_games,
            overwrite=overwrite,
            expected_sha256=expected_sha256,
            pre_publish_check=pre_publish_check,
        )
    else:  # pragma: no cover - exact enum construction makes this defensive only.
        raise TypeError("PGN save mode is invalid")

    return PgnSavePublication(snapshot=snapshot, saved=saved)


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
    snapshot = publication.snapshot
    saved = publication.saved
    if type(snapshot) is not PgnSaveSnapshot or type(saved) is not SourceFingerprint:
        raise TypeError("PGN save publication is malformed")
    if snapshot._session_ref() is not current:
        raise _stale("PGN save publication belongs to a different document session")

    # Exact replay after a successful owner-thread commit is harmless.  This is
    # checked before source-staleness because an unchanged Save can legitimately
    # produce the same fingerprint as its source generation.
    if current.source == saved and current._saved_digest == snapshot.content_digest:
        return current.view()

    # Ordinary edits do not mutate either source provenance or the saved
    # baseline.  A competing successful Save/Save As does.  Bind both values so
    # an older worker cannot later overwrite newer publication authority even if
    # a path happens to cycle back to the same source.
    if (
        current.source != snapshot.source_before
        or current._saved_digest != snapshot._saved_digest_before
    ):
        raise _stale("PGN source changed before the save publication could commit")

    if snapshot.mode is PgnSaveMode.SAVE:
        source = snapshot.source_before
        if source is None or Path(saved.path).absolute() != Path(source.path).absolute():
            raise _stale("Save publication does not match the captured source")
    elif snapshot.mode is not PgnSaveMode.SAVE_AS:
        raise TypeError("PGN save mode is invalid")

    # ``PgnDocumentSession`` owns these fields.  This companion module is the
    # only background-save friend boundary: it updates provenance only after the
    # canonical writer returned a verified SourceFingerprint.  No GameTree or
    # serializer state is fabricated here.
    current._source = saved
    if snapshot.mode is PgnSaveMode.SAVE_AS:
        current._source_overwrite_safe = True
        current._global_warnings = ()
    current._saved_digest = snapshot.content_digest

    # Mark the live workspace clean only when it is still exactly the generation
    # that was written.  If the user edited during the worker run, retain the
    # newer workspace baseline and let ``dirty`` compare it to the saved digest.
    if current.workspace.content_digest == snapshot.content_digest:
        current.workspace.mark_saved()

    current._document_revision += 1
    return current.view()


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
