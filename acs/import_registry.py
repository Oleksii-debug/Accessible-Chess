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
        if not isinstance(original, OSError):
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
        self._by_suffix: dict[str, ReadOnlyImporter] = {}
        self._format_name_by_suffix: dict[str, str] = {}
        self._registration_token_by_suffix: dict[str, object] = {}

    def _registration_snapshot(
        self,
    ) -> tuple[
        dict[str, ReadOnlyImporter],
        dict[str, str],
        dict[str, object],
    ]:
        """Capture the complete routing authority before adapter execution."""
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
        by_suffix, format_names, tokens = snapshot
        if (
            set(self._by_suffix) != set(by_suffix)
            or set(self._format_name_by_suffix) != set(format_names)
            or set(self._registration_token_by_suffix) != set(tokens)
        ):
            return False
        return all(
            self._by_suffix[suffix] is importer
            and self._format_name_by_suffix[suffix] == format_names[suffix]
            and self._registration_token_by_suffix[suffix] is tokens[suffix]
            for suffix, importer in by_suffix.items()
        )

    def _restore_registration_snapshot(
        self,
        snapshot: tuple[
            dict[str, ReadOnlyImporter],
            dict[str, str],
            dict[str, object],
        ],
    ) -> None:
        by_suffix, format_names, tokens = snapshot
        self._by_suffix.clear()
        self._by_suffix.update(by_suffix)
        self._format_name_by_suffix.clear()
        self._format_name_by_suffix.update(format_names)
        self._registration_token_by_suffix.clear()
        self._registration_token_by_suffix.update(tokens)

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
        ):
            raise ImportRegistryError("Importer suffix must be bounded safe extension text")
        return value

    def register(self, importer: ReadOnlyImporter, *, replace: bool = False) -> ImporterRegistration:
        format_name = importer.format_name
        if type(format_name) is not str or not format_name.strip():
            raise ImportRegistryError("Importer format_name must be non-empty exact text")
        suffixes = tuple(self._normalize_suffix(item) for item in importer.suffixes)
        if not suffixes:
            raise ImportRegistryError("Importer must declare at least one suffix")
        if len(set(suffixes)) != len(suffixes):
            raise ImportRegistryError("Importer declares duplicate suffixes")

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
        for suffix in [key for key, value in self._by_suffix.items() if value is importer]:
            del self._by_suffix[suffix]
            del self._format_name_by_suffix[suffix]
            del self._registration_token_by_suffix[suffix]

    def importer_for(self, path: str | Path) -> ReadOnlyImporter | None:
        return self._by_suffix.get(Path(path).suffix.lower())

    def inspect(self, path: str | Path) -> ImportReport:
        return self._inspect(path, batch_context=False)

    def _inspect(self, path: str | Path, *, batch_context: bool) -> ImportReport:
        source = Path(path)
        safe_source = report_safe_name(source)
        source_suffix = source.suffix.lower()
        importer = self._by_suffix.get(source_suffix)
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
        registered_format_name = self._format_name_by_suffix.get(source_suffix)
        registration_token = self._registration_token_by_suffix.get(source_suffix)
        if registered_format_name is None or registration_token is None:
            raise ImportRegistryError("Importer registration state is inconsistent")
        registration_snapshot = self._registration_snapshot()

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
                raise SourceMutationError(
                    f"Read-only importer left source unverifiable after inspection: {safe_source}"
                ) from verification_exc
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
        except BaseException:
            # Process-control signals remain authoritative, but they may not
            # leave adapter-owned mutations in the host-owned routing table.
            # Restore only registration authority, then re-raise the original
            # signal unchanged rather than converting it to batch evidence.
            if not self._registration_matches(registration_snapshot):
                self._restore_registration_snapshot(registration_snapshot)
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
        """Strict multi-source inspection; aborts on the first source error."""
        return [self.inspect(path) for path in paths]

    def inspect_batch(self, paths: Iterable[str | Path]) -> BatchInspection:
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
        for raw_path in paths:
            source = Path(raw_path)
            try:
                report = self._inspect(source, batch_context=True)
            except SourceReadCancelledError:
                # Cooperative source-read cancellation is a trusted control
                # signal even though it intentionally subclasses RuntimeError.
                # Do not turn Cancel into ordinary per-source batch evidence or
                # continue inspecting later sources after the caller stopped.
                raise
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
        return tuple(sorted(self._by_suffix))

    def registrations(self) -> tuple[ImporterRegistration, ...]:
        grouped: dict[int, tuple[ReadOnlyImporter, list[str]]] = {}
        for suffix, importer in self._by_suffix.items():
            key = id(importer)
            if key not in grouped:
                grouped[key] = (importer, [])
            grouped[key][1].append(suffix)
        return tuple(
            ImporterRegistration(importer=item[0], suffixes=tuple(sorted(item[1])))
            for item in grouped.values()
        )
