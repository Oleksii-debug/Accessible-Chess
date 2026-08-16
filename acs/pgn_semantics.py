from __future__ import annotations

"""Presentation-neutral PGN semantic boundary over the canonical GameTree model.

This module does not parse chess moves and does not own chess legality.  It
projects existing :mod:`acs.gametree` records into stable metadata/setup/result
values and typed diagnostics that storage, import and UI adapters can consume
without scraping human warning strings.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from .gametree import PgnGame, RESULTS


class DiagnosticSeverity(str, Enum):
    WARNING = "warning"
    ERROR = "error"


class PgnDiagnosticCode(str, Enum):
    INVALID_RESULT = "invalid_result"
    RESULT_MISMATCH = "result_mismatch"
    INVALID_SETUP = "invalid_setup"
    SETUP_REQUIRES_FEN = "setup_requires_fen"
    FEN_WITHOUT_SETUP = "fen_without_setup"
    MALFORMED_RECORD = "malformed_record"


@dataclass(frozen=True, slots=True)
class PgnDiagnostic:
    code: PgnDiagnosticCode
    severity: DiagnosticSeverity
    message: str
    source_index: int
    field: str | None = None


@dataclass(frozen=True, slots=True)
class PgnSetup:
    enabled: bool
    fen: str | None


@dataclass(frozen=True, slots=True)
class PgnTagSet:
    """Stable immutable tag projection preserving arbitrary PGN tags."""

    items: tuple[tuple[str, str], ...]

    @classmethod
    def from_game(cls, game: PgnGame) -> "PgnTagSet":
        return cls(tuple((str(key), str(value)) for key, value in game.tags.items()))

    def get(self, name: str, default: str | None = None) -> str | None:
        for key, value in self.items:
            if key == name:
                return value
        return default

    def as_dict(self) -> dict[str, str]:
        return dict(self.items)


@dataclass(frozen=True, slots=True)
class PgnSemanticRecord:
    source_index: int
    tags: PgnTagSet
    setup: PgnSetup
    result: str
    diagnostics: tuple[PgnDiagnostic, ...]

    @property
    def usable(self) -> bool:
        return not any(item.severity is DiagnosticSeverity.ERROR for item in self.diagnostics)


def _diagnostic(
    game: PgnGame,
    code: PgnDiagnosticCode,
    message: str,
    *,
    field: str | None = None,
    severity: DiagnosticSeverity = DiagnosticSeverity.WARNING,
) -> PgnDiagnostic:
    return PgnDiagnostic(
        code=code,
        severity=severity,
        message=message,
        source_index=game.source_index,
        field=field,
    )


def _setup_semantics(game: PgnGame, diagnostics: list[PgnDiagnostic]) -> PgnSetup:
    raw_setup = game.tags.get("SetUp")
    raw_fen = game.tags.get("FEN")
    setup = raw_setup.strip() if raw_setup is not None else None
    fen = raw_fen.strip() if raw_fen is not None and raw_fen.strip() else None

    if setup not in {None, "0", "1"}:
        diagnostics.append(
            _diagnostic(
                game,
                PgnDiagnosticCode.INVALID_SETUP,
                f"SetUp must be 0 or 1, got {raw_setup!r}",
                field="SetUp",
                severity=DiagnosticSeverity.ERROR,
            )
        )
        return PgnSetup(enabled=False, fen=fen)

    enabled = setup == "1"
    if enabled and fen is None:
        diagnostics.append(
            _diagnostic(
                game,
                PgnDiagnosticCode.SETUP_REQUIRES_FEN,
                "SetUp=1 requires a non-empty FEN tag",
                field="FEN",
                severity=DiagnosticSeverity.ERROR,
            )
        )
    elif fen is not None and not enabled:
        diagnostics.append(
            _diagnostic(
                game,
                PgnDiagnosticCode.FEN_WITHOUT_SETUP,
                "FEN is present without SetUp=1; preserve it but do not infer setup silently",
                field="SetUp",
            )
        )

    return PgnSetup(enabled=enabled, fen=fen)


def analyze_game(game: PgnGame) -> PgnSemanticRecord:
    """Return a typed semantic projection without mutating ``game``.

    Existing parser warnings are preserved as diagnostics.  Known result
    mismatch warnings receive a stable diagnostic code; other malformed-source
    warnings remain available under ``MALFORMED_RECORD`` rather than being
    discarded or converted into guessed structure.
    """

    diagnostics: list[PgnDiagnostic] = []
    tags = PgnTagSet.from_game(game)

    header_result = game.tags.get("Result")
    if header_result is not None and header_result not in RESULTS:
        diagnostics.append(
            _diagnostic(
                game,
                PgnDiagnosticCode.INVALID_RESULT,
                f"invalid Result tag {header_result!r}",
                field="Result",
                severity=DiagnosticSeverity.ERROR,
            )
        )

    for warning in game.warnings:
        if warning.startswith("header Result ") and " differs from movetext " in warning:
            code = PgnDiagnosticCode.RESULT_MISMATCH
            field = "Result"
        else:
            code = PgnDiagnosticCode.MALFORMED_RECORD
            field = None
        diagnostics.append(_diagnostic(game, code, warning, field=field))

    setup = _setup_semantics(game, diagnostics)
    return PgnSemanticRecord(
        source_index=game.source_index,
        tags=tags,
        setup=setup,
        result=game.result,
        diagnostics=tuple(diagnostics),
    )


def analyze_games(games: Iterable[PgnGame]) -> tuple[PgnSemanticRecord, ...]:
    return tuple(analyze_game(game) for game in games)
