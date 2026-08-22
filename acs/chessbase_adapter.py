from __future__ import annotations

"""Read-only adapter contract for ChessBase-family source files.

The adapter deliberately separates *recognition* from *decoding*. Filename and
component-family probing is safe and useful for provenance/import reports, but
it must never be presented as format compatibility. Proprietary source files
are immutable inputs; any future verified decoder must write to a new neutral
output such as GameTree/ACSDB/PGN.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


_PRIMARY_EXTENSIONS = {
    ".cbh": "ChessBase database header/component set",
    ".cbv": "ChessBase archive/container",
    ".cbf": "legacy ChessBase database",
    ".2cbh": "ChessBase 2CBH database",
    ".cbone": "ChessBase single-file database",
}

_COMPONENT_EXTENSIONS = {
    ".cbg": "game/move and variation data component",
    ".cba": "annotations/auxiliary component",
    ".cbp": "players index/component",
    ".cbt": "tournament index/component",
    ".cbc": "commentary/auxiliary component",
    ".cbs": "source/index auxiliary component",
}

_ALL_EXTENSIONS = {**_PRIMARY_EXTENSIONS, **_COMPONENT_EXTENSIONS}


def report_safe_path_name(path: str | Path) -> str:
    """Return a filename-only report identifier independent of host path syntax.

    ``Path.name`` follows the runner's native path grammar. On POSIX that means
    a Windows path such as ``C:\\Users\\Private\\db.cbh`` is treated as one
    filename and can leak workstation directories into serialized evidence.
    Report payloads must instead strip both slash conventions regardless of the
    machine performing the inspection.
    """

    normalized = str(path).replace("\\", "/").rstrip("/")
    if not normalized:
        return "source"
    return normalized.rsplit("/", 1)[-1] or "source"


class ChessBaseProbeIOError(RuntimeError):
    """Raised internally when companion topology cannot be observed safely."""


@dataclass(frozen=True)
class ChessBaseComponent:
    path: Path
    extension: str
    role: str
    exists: bool

    def as_report_fields(self) -> dict[str, object]:
        return {
            "path": report_safe_path_name(self.path),
            "extension": self.extension,
            "role": self.role,
            "exists": self.exists,
        }


@dataclass(frozen=True)
class ChessBaseSourceProbe:
    path: Path
    extension: str
    family_name: str
    recognized: bool
    read_only: bool = True
    decoder_available: bool = False
    status: str = "adapter_only"
    source_kind: str = "unknown"
    is_primary_source: bool = False
    components: tuple[ChessBaseComponent, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def safe_to_import(self) -> bool:
        return (
            self.recognized
            and self.is_primary_source
            and self.read_only
            and self.decoder_available
        )

    @property
    def existing_components(self) -> tuple[ChessBaseComponent, ...]:
        return tuple(component for component in self.components if component.exists)

    def as_report_fields(self) -> dict[str, object]:
        return {
            "source_path": report_safe_path_name(self.path),
            "extension": self.extension,
            "family_name": self.family_name,
            "recognized": self.recognized,
            "source_kind": self.source_kind,
            "is_primary_source": self.is_primary_source,
            "read_only": self.read_only,
            "decoder_available": self.decoder_available,
            "safe_to_import": self.safe_to_import,
            "status": self.status,
            "components": [item.as_report_fields() for item in self.components],
            "warnings": list(self.warnings),
        }


def _suffix(path: Path) -> str:
    return path.suffix.lower()


def _case_insensitive_directory_index(directory: Path) -> dict[str, Path]:
    """Return lowercase filename -> real path without mutating or opening files."""
    if not directory.exists() or not directory.is_dir():
        return {}
    try:
        return {entry.name.lower(): entry for entry in directory.iterdir() if entry.is_file()}
    except OSError as exc:
        raise ChessBaseProbeIOError("Companion directory is unavailable due to filesystem I/O") from exc


def _classic_cbh_components(source: Path) -> tuple[ChessBaseComponent, ...]:
    directory_index = _case_insensitive_directory_index(source.parent)
    stem = source.stem
    items: list[ChessBaseComponent] = []
    for extension, role in _COMPONENT_EXTENSIONS.items():
        expected_name = f"{stem}{extension}"
        real_path = directory_index.get(expected_name.lower(), source.with_suffix(extension))
        items.append(
            ChessBaseComponent(
                path=real_path,
                extension=extension,
                role=role,
                exists=expected_name.lower() in directory_index,
            )
        )
    return tuple(items)


def probe_chessbase_source(path: str | Path) -> ChessBaseSourceProbe:
    source = Path(path)
    extension = _suffix(source)
    family_name = _ALL_EXTENSIONS.get(extension, "unknown")
    recognized = extension in _ALL_EXTENSIONS
    is_primary = extension in _PRIMARY_EXTENSIONS
    topology_error = ""

    if extension == ".cbv":
        source_kind = "archive_container"
        components: tuple[ChessBaseComponent, ...] = ()
    elif extension == ".cbh":
        source_kind = "component_set"
        try:
            components = _classic_cbh_components(source)
        except ChessBaseProbeIOError as exc:
            components = ()
            topology_error = str(exc)
    elif extension in {".2cbh", ".cbone"}:
        source_kind = "single_file_database"
        components = ()
    elif extension == ".cbf":
        source_kind = "legacy_database"
        components = ()
    elif extension in _COMPONENT_EXTENSIONS:
        source_kind = "component"
        components = ()
    else:
        source_kind = "unknown"
        components = ()

    warnings: list[str] = []
    if not recognized:
        warnings.append("Unrecognized ChessBase-family extension; no import attempted.")
    elif not is_primary:
        warnings.append(
            "Recognized ChessBase component file only; select the database primary source "
            "(for example .cbh) rather than importing this component independently."
        )
        warnings.append(
            "No verified decoder is enabled; component recognition is provenance metadata only."
        )
    else:
        warnings.append(
            "Format family recognized by filename/component layout only; no verified decoder is enabled."
        )
        warnings.append(
            "Source must remain read-only; import must target ACSDB/PGN or another new output."
        )
        if extension == ".cbv":
            warnings.append(
                "CBV is treated as an archive/container, distinct from the classic CBH component family."
            )
        elif extension == ".cbh":
            if topology_error:
                warnings.append(topology_error + "; companion presence could not be verified.")
            else:
                found = [component.extension for component in components if component.exists]
                if found:
                    warnings.append(
                        "Classic CBH companion files detected: " + ", ".join(found) + "."
                    )
                else:
                    warnings.append(
                        "No classic CBH companion files were detected beside the header; database may be incomplete or unavailable."
                    )

    return ChessBaseSourceProbe(
        path=source,
        extension=extension,
        family_name=family_name,
        recognized=recognized,
        source_kind=source_kind,
        is_primary_source=is_primary,
        components=components,
        warnings=tuple(warnings),
    )


def probe_many(paths: Iterable[str | Path]) -> list[ChessBaseSourceProbe]:
    return [probe_chessbase_source(path) for path in paths]


def recognized_extensions() -> tuple[str, ...]:
    return tuple(sorted(_ALL_EXTENSIONS))


def primary_extensions() -> tuple[str, ...]:
    return tuple(sorted(_PRIMARY_EXTENSIONS))


def component_extensions() -> tuple[str, ...]:
    return tuple(sorted(_COMPONENT_EXTENSIONS))
