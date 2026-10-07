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

from .report_paths import report_safe_name


_PRIMARY_EXTENSIONS = {
    ".cbh": "ChessBase database header/component set",
    ".cbv": "ChessBase archive/container",
    ".cbf": "legacy ChessBase database",
    ".2cbh": "ChessBase 2CBH database",
    ".cbone": "ChessBase single-file database",
}

_CLASSIC_COMPONENT_EXTENSIONS = {
    ".cbg": "game/move and variation data component",
    ".cba": "annotations/auxiliary component",
    ".cbp": "players index/component",
    ".cbt": "tournament index/component",
    ".cbc": "commentary/auxiliary component",
    ".cbs": "source/index auxiliary component",
}

_LEGACY_CBF_COMPONENT_EXTENSIONS = {
    ".cbi": "legacy ChessBase index companion",
}

_COMPONENT_EXTENSIONS = {
    **_CLASSIC_COMPONENT_EXTENSIONS,
    **_LEGACY_CBF_COMPONENT_EXTENSIONS,
}
_ALL_EXTENSIONS = {**_PRIMARY_EXTENSIONS, **_COMPONENT_EXTENSIONS}


def _report_name(path: Path) -> str:
    """Compatibility wrapper around the shared cross-platform sanitizer."""
    return report_safe_name(path)


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
            "path": _report_name(self.path),
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
            "source_path": _report_name(self.path),
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


def _case_insensitive_directory_index(
    directory: Path,
    *,
    watched_names: Iterable[str] = (),
) -> dict[str, Path]:
    """Return case-folded filename -> real path and reject relevant collisions.

    An unrelated case-collision in a shared import directory must not poison a
    different database family. Only collisions for names that the caller is
    actually resolving are ambiguous and fail closed.
    """
    if not directory.exists() or not directory.is_dir():
        return {}
    watched = {name.casefold() for name in watched_names}
    try:
        result: dict[str, Path] = {}
        for entry in directory.iterdir():
            if not entry.is_file():
                continue
            folded = entry.name.casefold()
            previous = result.get(folded)
            if (
                folded in watched
                and previous is not None
                and previous.name != entry.name
            ):
                raise ChessBaseProbeIOError(
                    "Companion directory contains case-colliding filenames"
                )
            if previous is None:
                result[folded] = entry
        return result
    except ChessBaseProbeIOError:
        raise
    except OSError as exc:
        raise ChessBaseProbeIOError(
            "Companion directory is unavailable due to filesystem I/O"
        ) from exc


def _classic_cbh_components(source: Path) -> tuple[ChessBaseComponent, ...]:
    stem = source.stem
    expected_names = [
        f"{stem}{extension}" for extension in _CLASSIC_COMPONENT_EXTENSIONS
    ]
    directory_index = _case_insensitive_directory_index(
        source.parent,
        watched_names=expected_names,
    )
    items: list[ChessBaseComponent] = []
    for extension, role in _CLASSIC_COMPONENT_EXTENSIONS.items():
        expected_name = f"{stem}{extension}"
        real_path = directory_index.get(
            expected_name.casefold(), source.with_suffix(extension)
        )
        items.append(
            ChessBaseComponent(
                path=real_path,
                extension=extension,
                role=role,
                exists=expected_name.casefold() in directory_index,
            )
        )
    return tuple(items)


def _legacy_cbf_components(source: Path) -> tuple[ChessBaseComponent, ...]:
    """Observe the mandatory same-stem CBI index without claiming decode support."""
    expected_name = f"{source.stem}.cbi"
    directory_index = _case_insensitive_directory_index(
        source.parent,
        watched_names=(expected_name,),
    )
    real_path = directory_index.get(
        expected_name.casefold(), source.with_suffix(".cbi")
    )
    return (
        ChessBaseComponent(
            path=real_path,
            extension=".cbi",
            role=_LEGACY_CBF_COMPONENT_EXTENSIONS[".cbi"],
            exists=expected_name.casefold() in directory_index,
        ),
    )


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
    elif extension == ".2cbh":
        source_kind = "multi_file_database_unqualified_topology"
        components = ()
    elif extension == ".cbone":
        source_kind = "single_file_database"
        components = ()
    elif extension == ".cbf":
        source_kind = "legacy_two_file_database"
        try:
            components = _legacy_cbf_components(source)
        except ChessBaseProbeIOError as exc:
            components = ()
            topology_error = str(exc)
    elif extension in _COMPONENT_EXTENSIONS:
        source_kind = "component"
        components = ()
    else:
        source_kind = "unknown"
        components = ()

    warnings: list[str] = []
    if not recognized:
        warnings.append(
            "Unrecognized ChessBase-family extension; no import attempted."
        )
    elif not is_primary:
        warnings.append(
            "Recognized ChessBase component file only; select the database primary source "
            "(for example .cbh or .cbf) rather than importing this component independently."
        )
        warnings.append(
            "Component recognition is provenance/topology metadata only; it does not "
            "create standalone decoder support."
        )
    else:
        warnings.append(
            "Format family recognized by filename/component layout only; runtime decoder "
            "availability must be established separately."
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
                warnings.append(
                    topology_error + "; companion presence could not be verified."
                )
            else:
                found = [
                    component.extension
                    for component in components
                    if component.exists
                ]
                if found:
                    warnings.append(
                        "Classic CBH companion files detected: "
                        + ", ".join(found)
                        + "."
                    )
                else:
                    warnings.append(
                        "No classic CBH companion files were detected beside the header; "
                        "database may be incomplete or unavailable."
                    )
        elif extension == ".2cbh":
            warnings.append(
                "2CBH is a multi-file database family, but its complete companion map "
                "is not evidence-qualified in this adapter; family integrity and import "
                "must fail closed rather than treating the .2cbh primary as a whole database."
            )
        elif extension == ".cbone":
            warnings.append(
                "CBONE is a single-file database topology; filename recognition alone does "
                "not establish semantic decoder support."
            )
        elif extension == ".cbf":
            if topology_error:
                warnings.append(
                    topology_error + "; the mandatory CBF/CBI pair could not be verified."
                )
            elif components and components[0].exists:
                warnings.append(
                    "Legacy CBF/CBI pair detected; this proves source topology only, "
                    "not semantic decoder support."
                )
            else:
                warnings.append(
                    "Legacy CBF source is incomplete without a same-stem .cbi index companion."
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
