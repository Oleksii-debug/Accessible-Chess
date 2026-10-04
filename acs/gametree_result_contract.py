from __future__ import annotations

"""Result/terminal-position and versioned exchange contracts for canonical GameTree legality.

This module consumes the existing non-destructive legality projection rather than
introducing another chess rules implementation.  Only forced terminal outcomes
that can be proven from the canonical :class:`acs.chesscore.Board` position are
compared with PGN result metadata.  Decisive results on non-terminal positions
remain valid because resignation, timeout, adjudication, and agreement live
outside pure board-state inference.
"""

from dataclasses import dataclass
from enum import Enum

from .chesscore import Board
from .gametree import MAX_TREE_NODES, PgnGame, RESULTS
from .gametree_legality import GameTreeLegalityReport, validate_game_legality


LEGALITY_SNAPSHOT_VERSION = 1


class GameTreeTerminalKind(str, Enum):
    UNKNOWN = "unknown"
    ONGOING = "ongoing"
    CHECKMATE = "checkmate"
    STALEMATE = "stalemate"


class GameTreeResultCode(str, Enum):
    INVALID_RESULT = "invalid_result"
    MAINLINE_INCOMPLETE = "mainline_incomplete"
    FORCED_RESULT_MISMATCH = "forced_result_mismatch"


@dataclass(frozen=True, slots=True)
class ResultContractIssue:
    code: GameTreeResultCode
    message: str


@dataclass(frozen=True, slots=True)
class GameTreeResultContract:
    source_result: str
    mainline_complete: bool
    mainline_final_fen: str | None
    terminal_kind: GameTreeTerminalKind
    forced_result: str | None
    result_consistent: bool | None
    issues: tuple[ResultContractIssue, ...]


@dataclass(frozen=True, slots=True)
class GameTreeLegalitySnapshot:
    schema_version: int
    start_fen: str | None
    legality_complete: bool
    legal_move_count: int
    source_result: str
    mainline_complete: bool
    mainline_final_fen: str | None
    terminal_kind: GameTreeTerminalKind
    forced_result: str | None
    result_consistent: bool | None
    legality_issue_codes: tuple[str, ...]
    result_issue_codes: tuple[str, ...]


def _forced_terminal(board: Board) -> tuple[GameTreeTerminalKind, str | None]:
    if board.legal_moves():
        return GameTreeTerminalKind.ONGOING, None
    if board.in_check():
        return (
            GameTreeTerminalKind.CHECKMATE,
            "0-1" if board.turn == "w" else "1-0",
        )
    return GameTreeTerminalKind.STALEMATE, "1/2-1/2"


def analyze_result_contract(
    game: PgnGame,
    report: GameTreeLegalityReport | None = None,
) -> GameTreeResultContract:
    """Compare source result metadata only with board-forced terminal outcomes.

    The final mainline position is taken from the existing legality projection.
    Variations never change the mainline terminal state.  If the mainline could
    not be projected completely, terminal/result consistency stays unknown and
    the last known position is not misrepresented as the game ending.
    """

    if not isinstance(game, PgnGame):
        raise TypeError("result contract requires a PgnGame")
    if report is None:
        report = validate_game_legality(game)
    if not isinstance(report, GameTreeLegalityReport):
        raise TypeError("report must be a GameTreeLegalityReport")

    source_result = game.result
    issues: list[ResultContractIssue] = []
    if type(source_result) is not str or source_result not in RESULTS:
        issues.append(
            ResultContractIssue(
                GameTreeResultCode.INVALID_RESULT,
                f"PGN result must be one of {sorted(RESULTS)!r}; got {source_result!r}",
            )
        )

    moves = game.line.moves if hasattr(game.line, "moves") else None
    root_projections = tuple(
        move for move in report.moves if move.address.line_path == ()
    )
    mainline_complete = (
        type(moves) is list
        and len(root_projections) == len(moves)
        and tuple(move.address.move_index for move in root_projections)
        == tuple(range(len(moves)))
    )

    if not mainline_complete:
        issues.append(
            ResultContractIssue(
                GameTreeResultCode.MAINLINE_INCOMPLETE,
                "mainline terminal position is unknown because legality projection did not cover every root move",
            )
        )
        last_known_fen = (
            root_projections[-1].fen_after
            if root_projections
            else report.start_fen
        )
        return GameTreeResultContract(
            source_result=source_result,
            mainline_complete=False,
            mainline_final_fen=last_known_fen,
            terminal_kind=GameTreeTerminalKind.UNKNOWN,
            forced_result=None,
            result_consistent=None,
            issues=tuple(issues),
        )

    final_fen = (
        root_projections[-1].fen_after
        if root_projections
        else report.start_fen
    )
    if final_fen is None:
        issues.append(
            ResultContractIssue(
                GameTreeResultCode.MAINLINE_INCOMPLETE,
                "mainline terminal position is unavailable",
            )
        )
        return GameTreeResultContract(
            source_result=source_result,
            mainline_complete=False,
            mainline_final_fen=None,
            terminal_kind=GameTreeTerminalKind.UNKNOWN,
            forced_result=None,
            result_consistent=None,
            issues=tuple(issues),
        )

    board = Board(final_fen)
    terminal_kind, forced_result = _forced_terminal(board)
    result_consistent: bool | None = None
    if forced_result is not None:
        result_consistent = source_result == forced_result
        if not result_consistent:
            issues.append(
                ResultContractIssue(
                    GameTreeResultCode.FORCED_RESULT_MISMATCH,
                    f"source result {source_result!r} conflicts with forced board result {forced_result!r}",
                )
            )

    return GameTreeResultContract(
        source_result=source_result,
        mainline_complete=True,
        mainline_final_fen=final_fen,
        terminal_kind=terminal_kind,
        forced_result=forced_result,
        result_consistent=result_consistent,
        issues=tuple(issues),
    )


def create_legality_snapshot(game: PgnGame) -> GameTreeLegalitySnapshot:
    """Create one immutable versioned summary from canonical legality evidence."""

    report = validate_game_legality(game)
    result = analyze_result_contract(game, report)
    return GameTreeLegalitySnapshot(
        schema_version=LEGALITY_SNAPSHOT_VERSION,
        start_fen=report.start_fen,
        legality_complete=report.complete,
        legal_move_count=report.legal_move_count,
        source_result=result.source_result,
        mainline_complete=result.mainline_complete,
        mainline_final_fen=result.mainline_final_fen,
        terminal_kind=result.terminal_kind,
        forced_result=result.forced_result,
        result_consistent=result.result_consistent,
        legality_issue_codes=tuple(issue.code.value for issue in report.issues),
        result_issue_codes=tuple(issue.code.value for issue in result.issues),
    )


def legality_snapshot_to_payload(snapshot: GameTreeLegalitySnapshot) -> dict[str, object]:
    """Export a deterministic JSON-compatible payload without hidden coercion."""

    if not isinstance(snapshot, GameTreeLegalitySnapshot):
        raise TypeError("snapshot must be a GameTreeLegalitySnapshot")
    return {
        "schema_version": snapshot.schema_version,
        "start_fen": snapshot.start_fen,
        "legality_complete": snapshot.legality_complete,
        "legal_move_count": snapshot.legal_move_count,
        "source_result": snapshot.source_result,
        "mainline_complete": snapshot.mainline_complete,
        "mainline_final_fen": snapshot.mainline_final_fen,
        "terminal_kind": snapshot.terminal_kind.value,
        "forced_result": snapshot.forced_result,
        "result_consistent": snapshot.result_consistent,
        "legality_issue_codes": list(snapshot.legality_issue_codes),
        "result_issue_codes": list(snapshot.result_issue_codes),
    }


def _require_exact_bool(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{name} must be an exact boolean")
    return value


def _require_optional_bool(value: object, name: str) -> bool | None:
    if value is None:
        return None
    return _require_exact_bool(value, name)


def _require_optional_text(value: object, name: str) -> str | None:
    if value is None:
        return None
    if type(value) is not str:
        raise ValueError(f"{name} must be text or null")
    return value


def _require_code_list(value: object, name: str) -> tuple[str, ...]:
    if type(value) is not list:
        raise ValueError(f"{name} must be a list")
    if len(value) > MAX_TREE_NODES:
        raise ValueError(f"{name} exceeds the bounded issue count")
    if any(type(item) is not str or not item for item in value):
        raise ValueError(f"{name} must contain non-empty text codes")
    return tuple(value)


def legality_snapshot_from_payload(payload: object) -> GameTreeLegalitySnapshot:
    """Restore only the exact supported exchange schema; reject silent migration."""

    if type(payload) is not dict:
        raise ValueError("legality snapshot payload must be a dictionary")
    expected = {
        "schema_version",
        "start_fen",
        "legality_complete",
        "legal_move_count",
        "source_result",
        "mainline_complete",
        "mainline_final_fen",
        "terminal_kind",
        "forced_result",
        "result_consistent",
        "legality_issue_codes",
        "result_issue_codes",
    }
    if set(payload) != expected:
        missing = sorted(expected - set(payload))
        extra = sorted(set(payload) - expected)
        raise ValueError(f"legality snapshot fields mismatch; missing={missing!r} extra={extra!r}")

    version = payload["schema_version"]
    if type(version) is not int or version != LEGALITY_SNAPSHOT_VERSION:
        raise ValueError(f"unsupported legality snapshot schema_version: {version!r}")

    count = payload["legal_move_count"]
    if type(count) is not int or count < 0 or count > MAX_TREE_NODES:
        raise ValueError("legal_move_count must be an exact bounded non-negative integer")

    source_result = payload["source_result"]
    if type(source_result) is not str or source_result not in RESULTS:
        raise ValueError("source_result must be a canonical PGN result token")

    terminal_value = payload["terminal_kind"]
    if type(terminal_value) is not str:
        raise ValueError("terminal_kind must be text")
    try:
        terminal_kind = GameTreeTerminalKind(terminal_value)
    except ValueError as exc:
        raise ValueError(f"unsupported terminal_kind: {terminal_value!r}") from exc

    forced_result = _require_optional_text(payload["forced_result"], "forced_result")
    if forced_result is not None and forced_result not in RESULTS - {"*"}:
        raise ValueError("forced_result must be a decisive/draw PGN result token or null")

    result_consistent = _require_optional_bool(
        payload["result_consistent"], "result_consistent"
    )
    if forced_result is None and result_consistent is not None:
        raise ValueError("result_consistent must be null when no forced_result exists")

    mainline_complete = _require_exact_bool(
        payload["mainline_complete"], "mainline_complete"
    )
    if not mainline_complete and terminal_kind is not GameTreeTerminalKind.UNKNOWN:
        raise ValueError("incomplete mainline must use terminal_kind=unknown")

    return GameTreeLegalitySnapshot(
        schema_version=version,
        start_fen=_require_optional_text(payload["start_fen"], "start_fen"),
        legality_complete=_require_exact_bool(
            payload["legality_complete"], "legality_complete"
        ),
        legal_move_count=count,
        source_result=source_result,
        mainline_complete=mainline_complete,
        mainline_final_fen=_require_optional_text(
            payload["mainline_final_fen"], "mainline_final_fen"
        ),
        terminal_kind=terminal_kind,
        forced_result=forced_result,
        result_consistent=result_consistent,
        legality_issue_codes=_require_code_list(
            payload["legality_issue_codes"], "legality_issue_codes"
        ),
        result_issue_codes=_require_code_list(
            payload["result_issue_codes"], "result_issue_codes"
        ),
    )
