from __future__ import annotations

"""Read-only adapter contract for ChessBase-family source files.

This module deliberately does not decode proprietary formats yet.  It gives
Stage 2 a stable, presentation-neutral boundary for future verified decoders
without allowing callers to mistake extension recognition for compatibility.
Source files are always treated as immutable inputs.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


_RECOGNIZED_EXTENSIONS = {
    ".cbh": "ChessBase database header",
    ".cbv": "ChessBase archive",
    ".cbf": "legacy ChessBase database",
    ".2cbh": "ChessBase 2CBH database",
    ".cbone": "ChessBase single-file database",
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
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def safe_to_import(self) -> bool:
        """True only when a verified decoder exists, not merely on suffix match."""
        return self.recognized and self.read_only and self.decoder_available

    def as_report_fields(self) -> dict[str, object]:
        return {
            "source_path": str(self.path),
            "extension": self.extension,
            "family_name": self.family_name,
            "recognized": self.recognized,
            "read_only": self.read_only,
            "decoder_available": self.decoder_available,
            "safe_to_import": self.safe_to_import,
            "status": self.status,
            "warnings": list(self.warnings),
        }


def probe_chessbase_source(path: str | Path) -> ChessBaseSourceProbe:
    source = Path(path)
    name_lower = source.name.lower()

    # pathlib.Path.suffix returns '.2cbh' correctly for names such as db.2cbh.
    extension = source.suffix.lower()
    family_name = _RECOGNIZED_EXTENSIONS.get(extension, "unknown")
    recognized = extension in _RECOGNIZED_EXTENSIONS

    warnings: list[str] = []
    if recognized:
        warnings.append(
            "Format family recognized by filename only; no verified decoder is enabled."
        )
        warnings.append(
            "Source must remain read-only; import must target ACSDB/PGN or another new output."
        )
    else:
        warnings.append("Unrecognized ChessBase-family extension; no import attempted.")

    # Keep the original spelling/path for provenance.  No file is opened or mutated here.
    _ = name_lower
    return ChessBaseSourceProbe(
        path=source,
        extension=extension,
        family_name=family_name,
        recognized=recognized,
        warnings=tuple(warnings),
    )


def probe_many(paths: Iterable[str | Path]) -> list[ChessBaseSourceProbe]:
    """Probe sources independently so one damaged/unknown record cannot hide others."""
    return [probe_chessbase_source(path) for path in paths]


def recognized_extensions() -> tuple[str, ...]:
    return tuple(sorted(_RECOGNIZED_EXTENSIONS))
