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
import re
from typing import Iterable

from .import_contract import ImportReport, ReadOnlyImporter, SourceFingerprint, fingerprint


class ImportRegistryError(ValueError):
    pass


class SourceMutationError(ImportRegistryError):
    """Raised when a supposedly read-only adapter changes source bytes."""


class SourceProvenanceError(ImportRegistryError):
    """Raised when an adapter report does not describe the inspected source."""


class InvalidImporterError(ImportRegistryError):
    """Raised when an adapter does not satisfy the registration contract."""


class ImporterInspectionError(ImportRegistryError):
    """Raised when a read-only adapter fails without changing its source."""


class InvalidImportReportError(ImportRegistryError):
    """Raised when an adapter returns malformed or contradictory evidence."""


_SUFFIX_RE = re.compile(r"^\.[a-z0-9][a-z0-9_-]*$")


@dataclass(frozen=True)
class _ImporterBinding:
    importer: ReadOnlyImporter
    format_name: str
    declared_suffixes: tuple[str, ...]


@dataclass(frozen=True)
class ImporterRegistration:
    importer: ReadOnlyImporter
    suffixes: tuple[str, ...]

    def __post_init__(self) -> None:
        if isinstance(self.importer, type) or not callable(
            getattr(self.importer, "inspect", None)
        ):
            raise TypeError("registration importer must be a read-only importer instance")
        format_name = getattr(self.importer, "format_name", None)
        if (
            not isinstance(format_name, str)
            or not format_name.strip()
            or format_name != format_name.strip()
            or "\n" in format_name
            or "\r" in format_name
        ):
            raise ValueError("registration importer must have a stable format name")
        if (
            not isinstance(self.suffixes, tuple)
            or not self.suffixes
            or any(
                not isinstance(suffix, str)
                or _SUFFIX_RE.fullmatch(suffix) is None
                for suffix in self.suffixes
            )
            or len(set(self.suffixes)) != len(self.suffixes)
        ):
            raise ValueError("registration suffixes must be unique canonical extensions")


@dataclass(frozen=True)
class BatchInspectionItem:
    """One source result from a non-aborting multi-file import preflight."""

    path: Path
    report: ImportReport | None = None
    error: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.path, Path):
            raise TypeError("batch item path must be Path")
        if self.report is not None and not isinstance(self.report, ImportReport):
            raise TypeError("batch item report must be ImportReport or None")
        if not isinstance(self.error, str):
            raise TypeError("batch item error must be text")
        if self.error and not self.error.strip():
            raise ValueError("batch item error must not be whitespace")
        if self.report is not None:
            self.report.validate()
        if (self.report is None) == (not self.error):
            raise ValueError("batch item must contain exactly one report or error")

    @property
    def ok(self) -> bool:
        return self.report is not None and not self.error


@dataclass(frozen=True)
class BatchInspection:
    """Ordered results for every requested source, including routing failures."""

    items: tuple[BatchInspectionItem, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.items, tuple)
            or any(not isinstance(item, BatchInspectionItem) for item in self.items)
        ):
            raise TypeError("batch items must be a tuple of BatchInspectionItem")

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
    if not isinstance(left, SourceFingerprint) or not isinstance(
        right, SourceFingerprint
    ):
        return False
    try:
        return (
            Path(left.path).resolve() == Path(right.path).resolve()
            and left.size == right.size
            and left.sha256 == right.sha256
            and left.suffix == right.suffix
        )
    except (OSError, RuntimeError, ValueError):
        return False


class ImportRegistry:
    def __init__(self) -> None:
        self._by_suffix: dict[str, _ImporterBinding] = {}

    @staticmethod
    def _normalize_suffix(suffix: str) -> str:
        if not isinstance(suffix, str):
            raise InvalidImporterError("Importer suffix must be text")
        value = suffix.strip().casefold()
        if not value:
            raise InvalidImporterError("Importer suffix must not be empty")
        value = value if value.startswith(".") else "." + value
        if _SUFFIX_RE.fullmatch(value) is None:
            raise InvalidImporterError(
                "Importer suffix must be a canonical ASCII extension"
            )
        return value

    @classmethod
    def _validate_importer(
        cls,
        importer: ReadOnlyImporter,
    ) -> tuple[str, tuple[str, ...]]:
        if isinstance(importer, type):
            raise InvalidImporterError("Importer must be an instance, not a class")
        format_name = getattr(importer, "format_name", None)
        if (
            not isinstance(format_name, str)
            or not format_name.strip()
            or format_name != format_name.strip()
            or "\n" in format_name
            or "\r" in format_name
        ):
            raise InvalidImporterError(
                "Importer format_name must be stable non-empty single-line text"
            )
        declared_suffixes = getattr(importer, "suffixes", None)
        if not isinstance(declared_suffixes, tuple):
            raise InvalidImporterError("Importer suffixes must be a tuple")
        suffixes = tuple(cls._normalize_suffix(item) for item in declared_suffixes)
        if not suffixes:
            raise InvalidImporterError("Importer must declare at least one suffix")
        if len(set(suffixes)) != len(suffixes):
            raise InvalidImporterError("Importer declares duplicate suffixes")
        if not callable(getattr(importer, "inspect", None)):
            raise InvalidImporterError("Importer inspect operation must be callable")
        return format_name, suffixes

    def register(self, importer: ReadOnlyImporter, *, replace: bool = False) -> ImporterRegistration:
        if not isinstance(replace, bool):
            raise InvalidImporterError("replace must be boolean")
        format_name, suffixes = self._validate_importer(importer)

        collisions = [suffix for suffix in suffixes if suffix in self._by_suffix]
        if collisions and not replace:
            raise ImportRegistryError(
                "Importer suffix already registered: " + ", ".join(sorted(collisions))
            )
        binding = _ImporterBinding(importer, format_name, suffixes)
        for suffix in suffixes:
            self._by_suffix[suffix] = binding
        return ImporterRegistration(importer=importer, suffixes=suffixes)

    def unregister(self, importer: ReadOnlyImporter) -> None:
        suffixes = [
            key
            for key, binding in self._by_suffix.items()
            if binding.importer is importer
        ]
        if not suffixes:
            raise ImportRegistryError("Importer is not registered")
        for suffix in suffixes:
            del self._by_suffix[suffix]

    def importer_for(self, path: str | Path) -> ReadOnlyImporter | None:
        source = self._coerce_path(path)
        binding = self._by_suffix.get(source.suffix.casefold())
        return None if binding is None else binding.importer

    def inspect(self, path: str | Path) -> ImportReport:
        source = self._coerce_path(path)
        binding = self._by_suffix.get(source.suffix.casefold())
        if binding is None:
            raise ImportRegistryError(
                f"No read-only importer registered for suffix: {source.suffix.lower() or '<none>'}"
            )

        importer = binding.importer
        format_name, declared_suffixes = self._validate_importer(importer)
        if (
            format_name != binding.format_name
            or declared_suffixes != binding.declared_suffixes
        ):
            raise InvalidImporterError(
                "Importer metadata changed after registration"
            )
        before = fingerprint(source)
        report: object | None = None
        adapter_error: Exception | None = None
        try:
            report = importer.inspect(source)
        except Exception as exc:  # adapter boundary; source check still runs
            adapter_error = exc
        try:
            after = fingerprint(source)
        except Exception as exc:
            raise SourceMutationError(
                f"Read-only importer made source unavailable during inspection: {source}"
            ) from exc

        if not _same_source(before, after):
            raise SourceMutationError(
                f"Read-only importer modified source bytes during inspection: {source}"
            ) from adapter_error
        if adapter_error is not None:
            raise ImporterInspectionError(
                f"Importer {format_name} failed for {source}: "
                f"{self._safe_error_text(adapter_error)}"
            ) from adapter_error
        if not isinstance(report, ImportReport):
            raise InvalidImportReportError(
                f"Importer {format_name} returned a non-ImportReport result"
            )
        try:
            snapshot = report.detached()
        except (TypeError, ValueError) as exc:
            raise InvalidImportReportError(
                f"Importer {format_name} returned an invalid report"
            ) from exc
        if snapshot.format_name != format_name:
            raise InvalidImportReportError(
                f"Importer report format_name does not match registered adapter: {source}"
            )
        if not _same_source(before, snapshot.source):
            raise SourceProvenanceError(
                f"Importer report provenance does not match inspected source: {source}"
            )
        return snapshot

    def inspect_many(self, paths: Iterable[str | Path]) -> list[ImportReport]:
        """Strict multi-source inspection; aborts on the first source error."""
        sources = self._snapshot_paths(paths)
        return [self.inspect(path) for path in sources]

    def inspect_batch(self, paths: Iterable[str | Path]) -> BatchInspection:
        """Inspect every requested source without hiding later results.

        This is the preferred preflight for multi-file families such as classic
        ChessBase databases. An unknown suffix, missing file, adapter error,
        source mutation, or provenance mismatch is recorded against that exact
        source while remaining sources are still inspected. No source is
        silently skipped and no mutation is accepted as a successful result.
        """
        sources = self._snapshot_paths(paths)
        items: list[BatchInspectionItem] = []
        for source in sources:
            try:
                report = self.inspect(source)
            except Exception as exc:
                items.append(
                    BatchInspectionItem(
                        path=source,
                        error=self._safe_error_text(exc),
                    )
                )
            else:
                items.append(BatchInspectionItem(path=source, report=report))
        return BatchInspection(items=tuple(items))

    @property
    def registered_suffixes(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_suffix))

    def registrations(self) -> tuple[ImporterRegistration, ...]:
        grouped: dict[int, tuple[ReadOnlyImporter, list[str]]] = {}
        for suffix, binding in self._by_suffix.items():
            importer = binding.importer
            key = id(importer)
            if key not in grouped:
                grouped[key] = (importer, [])
            grouped[key][1].append(suffix)
        return tuple(
            ImporterRegistration(importer=item[0], suffixes=tuple(sorted(item[1])))
            for item in grouped.values()
        )

    @staticmethod
    def _coerce_path(path: str | Path) -> Path:
        if not isinstance(path, (str, Path)):
            raise ImportRegistryError("Source path must be text or Path")
        if isinstance(path, str) and "\x00" in path:
            raise ImportRegistryError("Source path must not contain NUL")
        return Path(path)

    @classmethod
    def _snapshot_paths(cls, paths: Iterable[str | Path]) -> tuple[Path, ...]:
        if isinstance(paths, (str, bytes, Path)):
            raise ImportRegistryError("paths must be an iterable of source paths")
        try:
            values = tuple(paths)
        except TypeError as exc:
            raise ImportRegistryError(
                "paths must be an iterable of source paths"
            ) from exc
        return tuple(cls._coerce_path(path) for path in values)

    @staticmethod
    def _safe_error_text(exc: Exception) -> str:
        try:
            message = str(exc)
        except Exception:
            message = "<unprintable error>"
        return message or type(exc).__name__
