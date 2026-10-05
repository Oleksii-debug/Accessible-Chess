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


@dataclass(frozen=True, slots=True)
class PgnSaveSnapshot:
    """Detached, exact document generation prepared for background publication."""

    mode: PgnSaveMode
    document_revision: int
    content_digest: str
    games: tuple[PgnGame, ...]
    source_before: SourceFingerprint | None
    source_overwrite_safe_before: bool
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


def _snapshot_digest(games: tuple[PgnGame, ...]) -> str:
    try:
        return PgnWorkspace(games).content_digest
    except (PgnWorkspaceError, TypeError, ValueError) as exc:
        raise _stale("PGN save snapshot is no longer canonical") from exc


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
    detached_digest = _snapshot_digest(games)
    after_digest = current.workspace.content_digest
    if before_digest != after_digest or detached_digest != before_digest:
        raise _stale("PGN content changed while the save snapshot was being captured")

    return PgnSaveSnapshot(
        mode=mode,
        document_revision=current.document_revision,
        content_digest=detached_digest,
        games=games,
        source_before=source,
        source_overwrite_safe_before=view.source_overwrite_safe,
        _session_ref=ref(current),
    )


def expected_pgn_destination_sha256(path: str | Path) -> str | None:
    """Fingerprint an existing destination for explicit Save-As replacement.

    This function is intentionally side-effect free and suitable for the same
    worker that performs publication, keeping potentially expensive destination
    hashing away from the Windows UI thread.
    """

    destination = Path(path)
    if not destination.exists():
        return None
    return fingerprint(destination).sha256


def publish_pgn_save_snapshot(
    snapshot: PgnSaveSnapshot,
    *,
    path: str | Path | None = None,
    overwrite: bool = False,
    expected_sha256: str | None = None,
) -> PgnSavePublication:
    """Publish a detached snapshot through the existing canonical PGN writer.

    This function never reads or mutates the live session.  It is therefore the
    worker-thread half of the transaction.
    """

    if type(snapshot) is not PgnSaveSnapshot:
        raise TypeError("PGN save publication requires an exact snapshot")
    if _snapshot_digest(snapshot.games) != snapshot.content_digest:
        raise _stale("PGN save snapshot content changed before publication")

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
            snapshot.games,
            overwrite=True,
            expected_sha256=source.sha256,
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
            snapshot.games,
            overwrite=overwrite,
            expected_sha256=expected_sha256,
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

    if current.source != snapshot.source_before:
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
    "PgnSaveMode",
    "PgnSavePublication",
    "PgnSaveSnapshot",
    "capture_pgn_save_snapshot",
    "commit_pgn_save_publication",
    "expected_pgn_destination_sha256",
    "publish_pgn_save_snapshot",
]
