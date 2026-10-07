from __future__ import annotations

"""Registration-based external import routing for Accessible Chess.

The registry is deliberately presentation-neutral. It maps source suffixes to
read-only importer adapters without exposing format-specific binary structures
to UI or ACSDB code. Adding a new verified importer should require
registration, not editing unrelated chess/database logic.

All inspections are guarded by immutable-source verification. Adapters receive
an existing source path, but the registry independently fingerprints the source
before and after inspection and rejects mismatched provenance. A decoder that
mutates its input or reports evidence for different bytes cannot silently pass
through the shared import boundary.
"""

from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Iterable

from .import_contract import (
    ImportReport,
    ReadOnlyImporter,
    SourceFingerprint,
    SourceReadCancelledError,
    fingerprint,
)
from .report_paths import report_safe_name


_MAX_IMPORT_SUFFIX_CHARS = 64
_MAX_IMPORT_SUFFIXES = 64
_MAX_IMPORT_FORMAT_NAME_CHARS = 256
_PASSIVE_OSERROR_TYPES = frozenset(
    {
        OSError,
        BlockingIOError,
        ChildProcessError,
        ConnectionError,
        BrokenPipeError,
        ConnectionAbortedError,
        ConnectionRefusedError,
        ConnectionResetError,
        FileExistsError,
        FileNotFoundError,
        InterruptedError,
        IsADirectoryError,
        NotADirectoryError,
        PermissionError,
        ProcessLookupError,
        TimeoutError,
    }
)


class ImportRegistryError(ValueError):
    pass


class SourceMutationError(ImportRegistryError):
    """Raised when a supposedly read-only adapter changes source bytes."""


class SourceProvenanceError(ImportRegistryError):
    """Raised when an adapter report does not describe the inspected source."""


class _AdapterInspectionFailure(Exception):
    """Batch-only envelope distinguishing adapter-owned text from registry evidence."""

    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error


class _SourcePathCoercionFailure(Exception):
    """Batch-only envelope for provider-owned ordinary PathLike conversion failure."""

    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error


@dataclass(frozen=True)
class ImporterRegistration:
    importer: ReadOnlyImporter
    suffixes: tuple[str, ...]


@dataclass(frozen=True)
class BatchInspectionItem:
    """One source result from a non-aborting multi-file import preflight."""

    path: Path
    report: ImportReport | None = None
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.report is not None and not self.error


@dataclass(frozen=True)
class BatchInspection:
    """Ordered results for every requested source, including routing failures."""

    items: tuple[BatchInspectionItem, ...]

    @property
    def reports(self) -> tuple[ImportReport, ...]:
        return tuple(item.report for item in self.items if item.report is not None)

    @property
    def errors(self) -> tuple[BatchInspectionItem, ...]:
        return tuple(item for item in self.items if not item.ok)

    @property
    def all_ok(self) -> bool:
        return bool(self.items) and not self.errors


def _same_source(left: SourceFingerprint, right: SourceFingerprint) -> bool:
    """Compare source identity without trusting adapter-generated path spelling."""
    return (
        Path(left.path).absolute() == Path(right.path).absolute()
        and left.size == right.size
        and left.sha256 == right.sha256
        and left.suffix.lower() == right.suffix.lower()
    )


def _batch_error_text(exc: Exception, source: Path) -> str:
    """Render batch evidence without exposing workstation/importer path text."""

    adapter_owned = isinstance(exc, _AdapterInspectionFailure)
    if adapter_owned:
        original = exc.error
        # Adapter-owned exception subclasses are active objects. Never inspect
        # custom OSError attributes while rendering bounded batch evidence:
        # properties such as filename/errno may execute provider code, mutate
        # host routing, or raise process-control values. Only exact built-in
        # OSError families are passive enough to expose bounded errno/name data.
        if type(original) not in _PASSIVE_OSERROR_TYPES:
            return f"Importer rejected source: {report_safe_name(source)}"
        exc = original

    if isinstance(exc, ImportRegistryError):
        # These are now registry-owned failures only: adapter-originated
        # exceptions are wrapped above before they reach batch rendering.
        return str(exc)
    if isinstance(exc, OSError):
        names: list[str] = []
        for attribute in ("filename", "filename2"):
            try:
                candidate = getattr(exc, attribute, None)
            except Exception:
                candidate = None
            if candidate is None:
                continue
            # Exact built-in OSError instances can still carry arbitrary
            # provider-owned objects in filename/filename2. Do not call
            # os.fspath()/str() through report_safe_name() for those payloads:
            # diagnostic rendering must never manufacture process-control or
            # execute provider hooks after an ordinary adapter failure.
            if type(candidate) not in (str, bytes):
                continue
            try:
                safe = report_safe_name(candidate)
            except Exception:
                continue
            if safe and safe not in names:
                names.append(safe)
        if not names:
            names.append(report_safe_name(source))

        try:
            errno = getattr(exc, "errno", None)
        except Exception:
            errno = None
        context = "Filesystem error"
        if isinstance(errno, int) and not isinstance(errno, bool):
            context += f" (errno {errno})"
        return f"{context}: {' -> '.join(names)}"

    return f"Importer rejected source: {report_safe_name(source)}"

class ImportRegistry:
    def __init__(self) -> None:
        # Registration is host authority. Serialize public registry operations
        # so another thread cannot report a successful route mutation that an
        # in-flight inspection later rolls back to its earlier snapshot.
        self._authority_lock = RLock()
        self._by_suffix: dict[str, ReadOnlyImporter] = {}
        self._format_name_by_suffix: dict[str, str] = {}
        self._registration_token_by_suffix: dict[str, object] = {}

    def _registration_state_is_passive(self) -> bool:
        """Reject active/corrupt routing containers before observing their data."""

        by_suffix = getattr(self, "_by_suffix", None)
        format_names = getattr(self, "_format_name_by_suffix", None)
        tokens = getattr(self, "_registration_token_by_suffix", None)
        if (
            type(by_suffix) is not dict
            or type(format_names) is not dict
            or type(tokens) is not dict
        ):
            return False

        mappings = (by_suffix, format_names, tokens)
        if any(type(key) is not str for mapping in mappings for key in mapping):
            return False
        if any(type(value) is not str for value in format_names.values()):
            return False
        if any(type(value) is not object for value in tokens.values()):
            return False

        keys = set(by_suffix)
        return keys == set(format_names) == set(tokens)

    def _registration_snapshot(
        self,
    ) -> tuple[
        dict[str, ReadOnlyImporter],
        dict[str, str],
        dict[str, object],
    ]:
        """Capture the complete routing authority before adapter execution."""
        if not self._registration_state_is_passive():
            raise ImportRegistryError("Importer registration state is inconsistent")
        return (
            dict(self._by_suffix),
            dict(self._format_name_by_suffix),
            dict(self._registration_token_by_suffix),
        )

    def _registration_matches(
        self,
        snapshot: tuple[
            dict[str, ReadOnlyImporter],
            dict[str, str],
            dict[str, object],
        ],
    ) -> bool:
        if not self._registration_state_is_passive():
            return False
        by_suffix, format_names, tokens = snapshot
        if (
            len(self._by_suffix) != len(by_suffix)
            or len(self._format_name_by_suffix) != len(format_names)
            or len(self._registration_token_by_suffix) != len(tokens)
        ):
            return False
        for suffix, importer in by_suffix.items():
            if self._by_suffix.get(suffix) is not importer:
                return False
            current_format = self._format_name_by_suffix.get(suffix)
            if type(current_format) is not str or current_format != format_names[suffix]:
                return False
            if self._registration_token_by_suffix.get(suffix) is not tokens[suffix]:
                return False
        return True

    def _restore_registration_snapshot(
        self,
        snapshot: tuple[
            dict[str, ReadOnlyImporter],
            dict[str, str],
            dict[str, object],
        ],
    ) -> None:
        # Never call clear/update on adapter-rebound containers: a dict subclass
        # or arbitrary mapping could execute hooks during the recovery path.
        by_suffix, format_names, tokens = snapshot
        self._by_suffix = dict(by_suffix)
        self._format_name_by_suffix = dict(format_names)
        self._registration_token_by_suffix = dict(tokens)

    def _coerce_source_path(
        self, path: str | Path, *, batch_context: bool = False
    ) -> Path:
        """Coerce one source path without letting PathLike code seize routing authority."""

        registration_snapshot = self._registration_snapshot()
        try:
            source = Path(path)
        except BaseException as exc:
            registration_changed = not self._registration_matches(registration_snapshot)
            if registration_changed:
                self._restore_registration_snapshot(registration_snapshot)
            if registration_changed and isinstance(exc, Exception):
                raise ImportRegistryError(
                    "Importer registration changed while reading source path"
                ) from exc
            if batch_context and isinstance(exc, Exception):
                # Provider-owned conversion exceptions are never host evidence,
                # even when the provider deliberately raises ImportRegistryError
                # or a subclass with active __str__ behavior.
                raise _SourcePathCoercionFailure(exc) from exc
            raise

        if not self._registration_matches(registration_snapshot):
            self._restore_registration_snapshot(registration_snapshot)
            raise ImportRegistryError(
                "Importer registration changed while reading source path"
            )
        return source

    @staticmethod
    def _normalize_suffix(suffix: str) -> str:
        if type(suffix) is not str:
            raise ImportRegistryError("Importer suffix must be exact text")
        value = suffix.strip().lower()
        if not value:
            raise ImportRegistryError("Importer suffix must not be empty")
        value = value if value.startswith(".") else "." + value
        if (
            len(value) > _MAX_IMPORT_SUFFIX_CHARS
            or "/" in value
            or "\\" in value
            or report_safe_name("source" + value) != "source" + value
            or Path("source" + value).suffix.lower() != value
        ):
            raise ImportRegistryError("Importer suffix must be bounded canonical extension text")
        return value

    def register(self, importer: ReadOnlyImporter, *, replace: bool = False) -> ImporterRegistration:
        with self._authority_lock:
            return self._register_locked(importer, replace=replace)

    def _register_locked(
        self, importer: ReadOnlyImporter, *, replace: bool = False
    ) -> ImporterRegistration:
        if type(replace) is not bool:
            raise ImportRegistryError("Importer replace flag must be boolean")

        # Importer metadata is adapter-owned code. Hold a host-owned routing
        # snapshot while properties/iterators are observed, bound the iterable,
        # and restore any re-entrant routing mutation before returning/raising.
        registration_snapshot = self._registration_snapshot()
        try:
            format_name = importer.format_name
            if type(format_name) is not str:
                raise ImportRegistryError("Importer format_name must be exact text")
            # Bound provider-owned exact text before strip() performs a linear
            # whitespace scan. Importer metadata is a routing/control-plane
            # boundary and must not permit unbounded work before registration.
            if len(format_name) > _MAX_IMPORT_FORMAT_NAME_CHARS:
                raise ImportRegistryError("Importer format_name is too long")
            if not format_name.strip():
                raise ImportRegistryError("Importer format_name must be non-empty exact text")

            raw_suffixes = importer.suffixes
            if type(raw_suffixes) is not tuple:
                raise ImportRegistryError(
                    "Importer suffixes must be an exact immutable tuple"
                )
            if len(raw_suffixes) > _MAX_IMPORT_SUFFIXES:
                raise ImportRegistryError("Importer declares too many suffixes")

            suffixes = tuple(self._normalize_suffix(item) for item in raw_suffixes)
            if not suffixes:
                raise ImportRegistryError("Importer must declare at least one suffix")
            if len(set(suffixes)) != len(suffixes):
                raise ImportRegistryError("Importer declares duplicate suffixes")
        except BaseException as exc:
            registration_changed = not self._registration_matches(registration_snapshot)
            if registration_changed:
                self._restore_registration_snapshot(registration_snapshot)
            if registration_changed and isinstance(exc, Exception):
                raise ImportRegistryError(
                    "Importer registration changed while reading importer metadata"
                ) from exc
            raise

        if not self._registration_matches(registration_snapshot):
            self._restore_registration_snapshot(registration_snapshot)
            raise ImportRegistryError(
                "Importer registration changed while reading importer metadata"
            )

        collisions = [suffix for suffix in suffixes if suffix in self._by_suffix]
        if collisions and not replace:
            raise ImportRegistryError(
                "Importer suffix already registered: " + ", ".join(sorted(collisions))
            )
        for suffix in suffixes:
            self._by_suffix[suffix] = importer
            self._format_name_by_suffix[suffix] = format_name
            self._registration_token_by_suffix[suffix] = object()
        return ImporterRegistration(importer=importer, suffixes=suffixes)

    def unregister(self, importer: ReadOnlyImporter) -> None:
        with self._authority_lock:
            self._unregister_locked(importer)

    def _unregister_locked(self, importer: ReadOnlyImporter) -> None:
        if not self._registration_state_is_passive():
            raise ImportRegistryError("Importer registration state is inconsistent")
        for suffix in [key for key, value in self._by_suffix.items() if value is importer]:
            del self._by_suffix[suffix]
            del self._format_name_by_suffix[suffix]
            del self._registration_token_by_suffix[suffix]

    def importer_for(self, path: str | Path) -> ReadOnlyImporter | None:
        with self._authority_lock:
            source = self._coerce_source_path(path)
            return self._by_suffix.get(source.suffix.lower())

    def inspect(self, path: str | Path) -> ImportReport:
        with self._authority_lock:
            return self._inspect(path, batch_context=False)

    def _inspect(self, path: str | Path, *, batch_context: bool) -> ImportReport:
        source = self._coerce_source_path(path)
        safe_source = report_safe_name(source)
        source_suffix = source.suffix.lower()

        # Linearize route selection at one host-owned snapshot. Previously the
        # importer was read first and the snapshot was captured afterwards, so
        # a concurrent replacement in that narrow window could make the old
        # importer execute under the new registration's identity/token.
        registration_snapshot = self._registration_snapshot()
        by_suffix, format_names, tokens = registration_snapshot
        importer = by_suffix.get(source_suffix)
        if importer is None:
            if (
                source_suffix
                and len(source_suffix) <= _MAX_IMPORT_SUFFIX_CHARS
                and "/" not in source_suffix
                and "\\" not in source_suffix
                and report_safe_name("source" + source_suffix) == "source" + source_suffix
            ):
                suffix_label = source_suffix
            else:
                suffix_label = "<none>" if not source_suffix else "<invalid>"
            raise ImportRegistryError(
                f"No read-only importer registered for suffix: {suffix_label}"
            )
        registered_format_name = format_names.get(source_suffix)
        registration_token = tokens.get(source_suffix)
        if registered_format_name is None or registration_token is None:
            raise ImportRegistryError("Importer registration state is inconsistent")

        before = fingerprint(source)
        try:
            report = importer.inspect(source)
        except Exception as exc:
            # Ordinary adapter failures must not bypass the read-only source
            # invariant. Registration is process authority, not adapter-owned
            # state: contain any re-entrant route mutation before observing the
            # source again or continuing a batch.
            registration_changed = not self._registration_matches(registration_snapshot)
            if registration_changed:
                self._restore_registration_snapshot(registration_snapshot)
            try:
                after = fingerprint(source)
            except Exception as verification_exc:
                # Cooperative Cancel is trusted control flow. If the adapter
                # deleted or otherwise made the source unverifiable before
                # cancelling, retain Cancel as the explicit cause so batch
                # preflight cannot downgrade it into ordinary evidence.
                cause = exc if isinstance(exc, SourceReadCancelledError) else verification_exc
                raise SourceMutationError(
                    f"Read-only importer left source unverifiable after inspection: {safe_source}"
                ) from cause
            if not _same_source(before, after):
                raise SourceMutationError(
                    f"Read-only importer modified source bytes during inspection: {safe_source}"
                ) from exc
            if isinstance(exc, SourceReadCancelledError):
                # Cooperative Cancel remains control flow after source integrity
                # has been proven. Registration authority was restored above,
                # so route drift must not downgrade Cancel into batch evidence
                # and allow later sources to continue.
                raise
            if registration_changed:
                raise ImportRegistryError(
                    "Read-only importer registration changed during inspection"
                ) from exc
            if batch_context:
                raise _AdapterInspectionFailure(exc) from exc
            raise
        except BaseException as exc:
            # Process-control signals remain authoritative only after the same
            # read-only source invariant has been proven. An adapter must not
            # bypass source-integrity verification by mutating/deleting the
            # source and then raising KeyboardInterrupt/SystemExit. Restore
            # host-owned routing first, verify the source, then propagate the
            # original signal unchanged when the source is still identical.
            if not self._registration_matches(registration_snapshot):
                self._restore_registration_snapshot(registration_snapshot)
            try:
                after = fingerprint(source)
            except Exception:
                # Preserve the direct process-control signal as the explicit
                # cause. Batch preflight uses that passive exception chain to
                # distinguish control-plus-mutation from ordinary per-source
                # adapter/source failures and must not continue afterwards.
                raise SourceMutationError(
                    f"Read-only importer left source unverifiable after inspection: {safe_source}"
                ) from exc
            if not _same_source(before, after):
                raise SourceMutationError(
                    f"Read-only importer modified source bytes during inspection: {safe_source}"
                ) from exc
            raise

        registration_changed = not self._registration_matches(registration_snapshot)
        if registration_changed:
            self._restore_registration_snapshot(registration_snapshot)
        try:
            after = fingerprint(source)
        except Exception as exc:
            raise SourceMutationError(
                f"Read-only importer left source unverifiable after inspection: {safe_source}"
            ) from exc

        if not _same_source(before, after):
            raise SourceMutationError(
                f"Read-only importer modified source bytes during inspection: {safe_source}"
            )
        if registration_changed:
            raise ImportRegistryError(
                "Read-only importer registration changed during inspection"
            )
        if type(report) is not ImportReport:
            raise ImportRegistryError(
                "Read-only importer must return an exact passive ImportReport"
            )
        try:
            report.validate()
        except (TypeError, ValueError) as exc:
            raise ImportRegistryError(
                "Read-only importer returned an invalid ImportReport"
            ) from exc
        if report.format_name != registered_format_name:
            raise ImportRegistryError(
                "Read-only importer report format identity does not match registered importer"
            )
        if not _same_source(before, report.source):
            raise SourceProvenanceError(
                f"Importer report provenance does not match inspected source: {safe_source}"
            )
        return report

    def inspect_many(self, paths: Iterable[str | Path]) -> list[ImportReport]:
        """Strict multi-source inspection; aborts on the first source error.

        The outer iterable is provider-owned input too. Reuse the same
        host-authority iterator fence as non-aborting batch preflight so
        iterator creation/advance cannot silently replace canonical routing
        between otherwise strict source inspections.
        """
        with self._authority_lock:
            return [self._inspect(path, batch_context=False) for path in self._iter_batch_paths(paths)]

    def _iter_batch_paths(
        self, paths: Iterable[str | Path]
    ) -> Iterable[str | Path]:
        """Advance provider-owned batch iterables without surrendering routing authority."""

        registration_snapshot = self._registration_snapshot()
        try:
            iterator = iter(paths)
        except BaseException as exc:
            registration_changed = not self._registration_matches(registration_snapshot)
            if registration_changed:
                self._restore_registration_snapshot(registration_snapshot)
            if registration_changed and isinstance(exc, Exception):
                raise ImportRegistryError(
                    "Importer registration changed while reading batch source iterable"
                ) from exc
            raise

        if not self._registration_matches(registration_snapshot):
            self._restore_registration_snapshot(registration_snapshot)
            raise ImportRegistryError(
                "Importer registration changed while reading batch source iterable"
            )

        while True:
            registration_snapshot = self._registration_snapshot()
            try:
                raw_path = next(iterator)
            except StopIteration:
                if not self._registration_matches(registration_snapshot):
                    self._restore_registration_snapshot(registration_snapshot)
                    raise ImportRegistryError(
                        "Importer registration changed while reading batch source iterable"
                    )
                return
            except BaseException as exc:
                registration_changed = not self._registration_matches(registration_snapshot)
                if registration_changed:
                    self._restore_registration_snapshot(registration_snapshot)
                if registration_changed and isinstance(exc, Exception):
                    raise ImportRegistryError(
                        "Importer registration changed while reading batch source iterable"
                    ) from exc
                raise

            if not self._registration_matches(registration_snapshot):
                self._restore_registration_snapshot(registration_snapshot)
                raise ImportRegistryError(
                    "Importer registration changed while reading batch source iterable"
                )
            yield raw_path

    def inspect_batch(self, paths: Iterable[str | Path]) -> BatchInspection:
        with self._authority_lock:
            return self._inspect_batch_locked(paths)

    def _inspect_batch_locked(self, paths: Iterable[str | Path]) -> BatchInspection:
        """Inspect every requested source without hiding later results.

        This is the preferred preflight for multi-file families such as classic
        ChessBase databases. An unknown suffix, missing file, adapter error,
        source mutation, provenance mismatch, or importer runtime failure is
        recorded against that exact source while remaining sources are still
        inspected. No source is silently skipped and no mutation is accepted as
        a successful result. Process-control exceptions are intentionally not
        swallowed.
        """
        items: list[BatchInspectionItem] = []
        for raw_path in self._iter_batch_paths(paths):
            try:
                source = self._coerce_source_path(raw_path, batch_context=True)
            except _SourcePathCoercionFailure:
                items.append(
                    BatchInspectionItem(
                        path=Path("<invalid-source>"),
                        error="Invalid source path",
                    )
                )
                continue
            except ImportRegistryError as exc:
                # A PathLike that re-enters the registry is an authority
                # violation, not a new routing baseline. The helper restores
                # host-owned state before this bounded evidence is published.
                items.append(
                    BatchInspectionItem(
                        path=Path("<invalid-source>"),
                        error=str(exc),
                    )
                )
                continue
            except Exception:
                # Path coercion is per-source ingress. An invalid/active
                # PathLike must not abort the whole batch or leak its exception
                # text; direct BaseException process-control remains unswallowed.
                items.append(
                    BatchInspectionItem(
                        path=Path("<invalid-source>"),
                        error="Invalid source path",
                    )
                )
                continue
            try:
                report = self._inspect(source, batch_context=True)
            except SourceReadCancelledError:
                # Cooperative source-read cancellation is a trusted control
                # signal even though it intentionally subclasses RuntimeError.
                # Do not turn Cancel into ordinary per-source batch evidence or
                # continue inspecting later sources after the caller stopped.
                raise
            except SourceMutationError as exc:
                # Ordinary source mutation remains bounded per-source evidence,
                # but mutation coupled to trusted control flow is fail-closed
                # for the whole batch. Otherwise cooperative Cancel or direct
                # process-control could be converted into a normal continue path.
                cause = exc.__cause__
                if isinstance(cause, SourceReadCancelledError) or (
                    isinstance(cause, BaseException) and not isinstance(cause, Exception)
                ):
                    raise
                message = _batch_error_text(exc, source)
                items.append(BatchInspectionItem(path=source, error=message))
            except Exception as exc:
                # Batch preflight is deliberately non-aborting for ordinary
                # failures, but adapter exception text is not a safe reporting
                # channel: it can contain workstation or decoder-side paths.
                # Process-control BaseException values remain unswallowed.
                message = _batch_error_text(exc, source)
                items.append(BatchInspectionItem(path=source, error=message))
            else:
                items.append(BatchInspectionItem(path=source, report=report))
        return BatchInspection(items=tuple(items))

    @property
    def registered_suffixes(self) -> tuple[str, ...]:
        with self._authority_lock:
            by_suffix, _, _ = self._registration_snapshot()
            return tuple(sorted(by_suffix))

    def registrations(self) -> tuple[ImporterRegistration, ...]:
        with self._authority_lock:
            return self._registrations_locked()

    def _registrations_locked(self) -> tuple[ImporterRegistration, ...]:
        by_suffix, _, _ = self._registration_snapshot()
        grouped: dict[int, tuple[ReadOnlyImporter, list[str]]] = {}
        for suffix, importer in by_suffix.items():
            key = id(importer)
            if key not in grouped:
                grouped[key] = (importer, [])
            grouped[key][1].append(suffix)
        return tuple(
            ImporterRegistration(importer=item[0], suffixes=tuple(sorted(item[1])))
            for item in grouped.values()
        )
