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

from .import_contract import ImportReport, ReadOnlyImporter, SourceFingerprint, fingerprint


class ImportRegistryError(ValueError):
    pass


class SourceMutationError(ImportRegistryError):
    """Raised when a supposedly read-only adapter changes source bytes."""


class SourceProvenanceError(ImportRegistryError):
    """Raised when an adapter report does not describe the inspected source."""


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


class ImportRegistry:
    def __init__(self) -> None:
        self._by_suffix: dict[str, ReadOnlyImporter] = {}
        self._format_name_by_suffix: dict[str, str] = {}

    @staticmethod
    def _normalize_suffix(suffix: str) -> str:
        if type(suffix) is not str:
            raise ImportRegistryError("Importer suffix must be exact text")
        value = suffix.strip().lower()
        if not value:
            raise ImportRegistryError("Importer suffix must not be empty")
        return value if value.startswith(".") else "." + value

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
        return ImporterRegistration(importer=importer, suffixes=suffixes)

    def unregister(self, importer: ReadOnlyImporter) -> None:
        for suffix in [key for key, value in self._by_suffix.items() if value is importer]:
            del self._by_suffix[suffix]
            del self._format_name_by_suffix[suffix]

    def importer_for(self, path: str | Path) -> ReadOnlyImporter | None:
        return self._by_suffix.get(Path(path).suffix.lower())

    def inspect(self, path: str | Path) -> ImportReport:
        source = Path(path)
        importer = self.importer_for(source)
        if importer is None:
            raise ImportRegistryError(
                f"No read-only importer registered for suffix: {source.suffix.lower() or '<none>'}"
            )

        before = fingerprint(source)
        report = importer.inspect(source)
        after = fingerprint(source)

        if not _same_source(before, after):
            raise SourceMutationError(
                f"Read-only importer modified source bytes during inspection: {source}"
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
        registered_format_name = self._format_name_by_suffix[source.suffix.lower()]
        if report.format_name != registered_format_name:
            raise ImportRegistryError(
                "Read-only importer report format identity does not match registered importer"
            )
        if not _same_source(before, report.source):
            raise SourceProvenanceError(
                f"Importer report provenance does not match inspected source: {source}"
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
                report = self.inspect(source)
            except Exception as exc:
                # Batch preflight is deliberately non-aborting for ordinary
                # adapter/parser failures. Process-control exceptions such as
                # KeyboardInterrupt/SystemExit inherit BaseException and are
                # intentionally not swallowed here.
                try:
                    message = str(exc).strip()
                except Exception:
                    # Exception rendering is adapter-controlled too: a hostile
                    # or broken __str__ must not turn recovery into a second
                    # batch-aborting failure.
                    message = ""
                if not message:
                    try:
                        fallback = type(exc).__name__.strip()
                    except Exception:
                        fallback = ""
                    message = fallback or "Exception"
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
