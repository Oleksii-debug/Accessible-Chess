from __future__ import annotations

"""Registration-based external import routing for Accessible Chess.

The registry is deliberately presentation-neutral.  It maps source suffixes to
read-only importer adapters without exposing format-specific binary structures
to UI or ACSDB code.  Adding a new verified importer should require
registration, not editing unrelated chess/database logic.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .import_contract import ImportReport, ReadOnlyImporter


class ImportRegistryError(ValueError):
    pass


@dataclass(frozen=True)
class ImporterRegistration:
    importer: ReadOnlyImporter
    suffixes: tuple[str, ...]


class ImportRegistry:
    def __init__(self) -> None:
        self._by_suffix: dict[str, ReadOnlyImporter] = {}

    @staticmethod
    def _normalize_suffix(suffix: str) -> str:
        value = suffix.strip().lower()
        if not value:
            raise ImportRegistryError("Importer suffix must not be empty")
        return value if value.startswith(".") else "." + value

    def register(self, importer: ReadOnlyImporter, *, replace: bool = False) -> ImporterRegistration:
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
        return ImporterRegistration(importer=importer, suffixes=suffixes)

    def unregister(self, importer: ReadOnlyImporter) -> None:
        for suffix in [key for key, value in self._by_suffix.items() if value is importer]:
            del self._by_suffix[suffix]

    def importer_for(self, path: str | Path) -> ReadOnlyImporter | None:
        return self._by_suffix.get(Path(path).suffix.lower())

    def inspect(self, path: str | Path) -> ImportReport:
        source = Path(path)
        importer = self.importer_for(source)
        if importer is None:
            raise ImportRegistryError(
                f"No read-only importer registered for suffix: {source.suffix.lower() or '<none>'}"
            )
        return importer.inspect(source)

    def inspect_many(self, paths: Iterable[str | Path]) -> list[ImportReport]:
        # Never collapse or skip a source: callers receive one report or one
        # explicit routing error for every requested path.
        return [self.inspect(path) for path in paths]

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
