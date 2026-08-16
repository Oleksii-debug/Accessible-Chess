from __future__ import annotations

"""Presentation-neutral PGN semantic boundary over the canonical GameTree model.

This module does not parse chess moves and does not own chess legality. It
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
    DUPLICATE_TAG = "duplicate_tag"
    DUPLICATE_RESULT = "duplicate_result"
    UNTERMINATED_COMMENT = "unterminated_comment"
    UNTERMINATED_VARIATION = "unterminated_variation"
    UNMATCHED_PARENTHESES = "unmatched_parentheses"
    ORPHAN_ANNOTATION = "orphan_annotation"
    UNSUPPORTED_TOKEN = "unsupported_token"
    TRAILING_MOVETEXT = "trailing_movetext"
    MALFORMED_RECORD = "malformed_record"


@dataclass(frozen=True, slots=True)
class PgnDiagnostic:
    code: PgnDiagnosticCode
    severity: DiagnosticSeverity
    message: str
    source_index: int
    field: str | None = None
    token_index: int | None = None


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

    @property
    def warning_count(self) -> int:
        return sum(item.severity is DiagnosticSeverity.WARNING for item in self.diagnostics)

    @property
    def error_count(self) -> int:
        return sum(item.severity is DiagnosticSeverity.ERROR for item in self.diagnostics)


def _diagnostic(
    game: PgnGame,
    code: PgnDiagnosticCode,
    message: str,
    *,
    field: str | None = None,
    severity: DiagnosticSeverity = DiagnosticSeverity.WARNING,
    token_index: int | None = None,
) -> PgnDiagnostic:
    return PgnDiagnostic(
        code=code,
        severity=severity,
        message=message,
        source_index=game.source_index,
        field=field,
        token_index=token_index,
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


_PARSER_CODE_MAP: dict[str, PgnDiagnosticCode] = {
    "result-mismatch": PgnDiagnosticCode.RESULT_MISMATCH,
    "duplicate-tag": PgnDiagnosticCode.DUPLICATE_TAG,
    "duplicate-result": PgnDiagnosticCode.DUPLICATE_RESULT,
    "unterminated-rav": PgnDiagnosticCode.UNTERMINATED_VARIATION,
    "unmatched-rparen": PgnDiagnosticCode.UNMATCHED_PARENTHESES,
    "orphan-nag": PgnDiagnosticCode.ORPHAN_ANNOTATION,
    "orphan-move-number": PgnDiagnosticCode.ORPHAN_ANNOTATION,
    "orphan-rav": PgnDiagnosticCode.ORPHAN_ANNOTATION,
    "unsupported-token": PgnDiagnosticCode.UNSUPPORTED_TOKEN,
    "movetext-after-result": PgnDiagnosticCode.TRAILING_MOVETEXT,
}


def _project_parser_diagnostics(game: PgnGame) -> list[PgnDiagnostic]:
    projected: list[PgnDiagnostic] = []
    if game.diagnostics:
        for item in game.diagnostics:
            if item.code == "token-warning" and item.message == "unterminated brace comment":
                code = PgnDiagnosticCode.UNTERMINATED_COMMENT
            else:
                code = _PARSER_CODE_MAP.get(item.code, PgnDiagnosticCode.MALFORMED_RECORD)
            field = "Result" if code in {PgnDiagnosticCode.RESULT_MISMATCH, PgnDiagnosticCode.DUPLICATE_RESULT} else None
            projected.append(
                _diagnostic(
                    game,
                    code,
                    item.message,
                    field=field,
                    token_index=item.token_index,
                )
            )
        return projected

    # Backward compatibility for PgnGame objects constructed by older callers.
    for warning in game.warnings:
        if warning.startswith("header Result ") and " differs from movetext " in warning:
            code = PgnDiagnosticCode.RESULT_MISMATCH
            field = "Result"
        elif warning == "unterminated brace comment":
            code = PgnDiagnosticCode.UNTERMINATED_COMMENT
            field = None
        else:
            code = PgnDiagnosticCode.MALFORMED_RECORD
            field = None
        projected.append(_diagnostic(game, code, warning, field=field))
    return projected


def analyze_game(game: PgnGame) -> PgnSemanticRecord:
    """Return a typed semantic projection without mutating ``game``."""

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

    diagnostics.extend(_project_parser_diagnostics(game))
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
