from __future__ import annotations

"""Host-facing private staging authority for encrypted CBZ imports.

This module does not decode ChessBase semantics and does not make CBZ a
supported user-facing format.  It composes the already-qualified CBZ extractor
and stale-workspace recovery primitives so one trusted application-owned root
owns the complete temporary lifetime of an encrypted import attempt.

The key contract is intentionally narrow:

* the Windows/application host supplies one explicit absolute recovery root;
* password capture is delegated to a one-shot provider and is never persisted,
  placed in argv/environment, or returned in events;
* the existing ``extract_cbz_external`` implementation remains the only CBZ
  decrypt/extract implementation;
* extracted proprietary files remain inside a marker-qualified outer workspace
  while the canonical importer consumes them;
* normal exit/cancel/error removes that outer workspace;
* a hard process termination can leave only that marker-qualified workspace,
  which the existing startup recovery preflight can identify on restart.

A Python ``str`` returned by the password provider remains immutable and cannot
be guaranteed wiped from interpreter/provider memory.  This module reduces
retention and provides the correct host seam, but does not claim impossible
memory-erasure guarantees.
"""

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import os
import threading
from typing import Callable, Iterator

from .cbv_extractor import CbvExtractError, ExternalCbvExtractorConfig, _validate_real_directory
from .cbz_extractor import (
    CbzExtraction,
    CbzExtractCode,
    CbzExtractError,
    _cleanup_private_workspace,
    _make_private_workspace,
    extract_cbz_external,
)
from .version2_windows_cbz_recovery_host import Version2WindowsCbzRecoveryPreflight


@dataclass(frozen=True, slots=True)
class CbzPasswordRequest:
    """Path-free request contract for future accessible password UI adapters."""

    format_name: str = "CBZ"
    masked_input_required: bool = True
    persistence_allowed: bool = False
    command_line_allowed: bool = False


PasswordProvider = Callable[[CbzPasswordRequest], str | None]


@dataclass(frozen=True, slots=True)
class CbzHostStagingAuthority:
    """Bind CBZ temporary extraction and restart recovery to one trusted root.

    ``recovery_root`` is an application-owned directory, not a browser/user
    payload.  The normal Windows composition should construct one authority at
    startup, run ``recovery_preflight()`` before exposing import UI, and use
    ``stage_for_canonical_import()`` for every encrypted CBZ attempt.
    """

    recovery_root: Path

    def __post_init__(self) -> None:
        root = self.recovery_root
        if type(root) is not Path or not root.is_absolute():
            raise CbzExtractError(
                "CBZ staging root must be an explicit absolute Path",
                code=CbzExtractCode.RECOVERY_ROOT_INVALID,
            )
        try:
            validated = _validate_real_directory(root, must_be_empty=False)
        except CbvExtractError as exc:
            raise CbzExtractError(
                "CBZ staging root is not a trusted real directory",
                code=CbzExtractCode.RECOVERY_ROOT_INVALID,
            ) from exc
        object.__setattr__(self, "recovery_root", validated)

    def recovery_preflight(self) -> Version2WindowsCbzRecoveryPreflight:
        """Return the existing one-shot startup preflight for this exact root."""

        return Version2WindowsCbzRecoveryPreflight(self.recovery_root)

    @contextmanager
    def stage_for_canonical_import(
        self,
        path: str | Path,
        config: ExternalCbvExtractorConfig,
        password_provider: PasswordProvider,
        *,
        cancel_event: threading.Event | None = None,
    ) -> Iterator[CbzExtraction]:
        """Yield one bounded extracted CBH-family stage, then erase it.

        The yielded paths are valid only inside this context.  A caller must
        perform canonical legality/GameTree/Library consumption before leaving
        the context.  No source path or secret is copied into the password
        request or returned host state.
        """

        if not callable(password_provider):
            raise TypeError("password_provider must be callable")
        if cancel_event is not None and cancel_event.is_set():
            raise CbzExtractError(
                "CBZ import was cancelled before password entry",
                code=CbzExtractCode.CANCELLED,
            )

        outer_workspace = _make_private_workspace(self.recovery_root)
        published = outer_workspace / "published"
        try:
            published.mkdir()
            if os.name != "nt":
                published.chmod(0o700)
        except OSError as exc:
            try:
                _cleanup_private_workspace(outer_workspace)
            except CbzExtractError:
                pass
            raise CbzExtractError(
                "CBZ private host stage could not be created",
                code=CbzExtractCode.OUTPUT_INVALID,
            ) from exc

        password: str | None = None
        try:
            request = CbzPasswordRequest()
            try:
                password = password_provider(request)
            except Exception as exc:
                raise CbzExtractError(
                    "CBZ password provider failed",
                    code=CbzExtractCode.PASSWORD_INVALID,
                ) from exc

            if password is None:
                raise CbzExtractError(
                    "CBZ password entry was cancelled",
                    code=CbzExtractCode.CANCELLED,
                )
            if type(password) is not str:
                raise CbzExtractError(
                    "CBZ password provider returned an invalid value",
                    code=CbzExtractCode.PASSWORD_INVALID,
                )
            if cancel_event is not None and cancel_event.is_set():
                raise CbzExtractError(
                    "CBZ import was cancelled before decrypt",
                    code=CbzExtractCode.CANCELLED,
                )

            result = extract_cbz_external(
                path,
                published,
                config,
                password,
                cancel_event=cancel_event,
            )

            # The wrapped extractor must not escape the marker-qualified outer
            # workspace.  Fail closed if future refactors violate this host
            # lifecycle invariant.
            try:
                result.primary_path.relative_to(published)
            except ValueError as exc:
                raise CbzExtractError(
                    "CBZ staged output escaped the private host workspace",
                    code=CbzExtractCode.OUTPUT_INVALID,
                ) from exc

            yield result
        finally:
            # Drop the local immutable reference as early as possible.  The
            # provider/interpreter may retain its own str; no false wiping claim
            # is made.  All decrypted/extracted filesystem material is removed
            # on ordinary lifecycle paths.
            password = None
            _cleanup_private_workspace(outer_workspace)
