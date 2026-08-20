from __future__ import annotations

"""Non-destructive legality projection for structural PGN GameTrees.

The parser deliberately preserves damaged or unusual source structure without
requiring chess legality.  This module is the separate, presentation-neutral
linking pass: it resolves each SAN token against an immutable parent position,
including nested RAV branches, while leaving the source GameTree untouched.
"""

from dataclasses import dataclass
from enum import Enum

from .chesscore import Board, Move, sq_name
from .gametree import (
    MAX_TREE_NODES,
    MAX_VARIATION_DEPTH,
    MoveNode,
    PgnGame,
    PgnRecoveryCode,
    PgnRecoveryIssue,
    RESULTS,
    VariationLine,
)


class LegalityContractCode(str, Enum):
    INVALID_GAME = "invalid_game"
    INVALID_TREE = "invalid_tree"
    GRAPH_CYCLE = "graph_cycle"
    GRAPH_REUSE = "graph_reuse"
    GRAPH_DEPTH_LIMIT = "graph_depth_limit"
    GRAPH_NODE_LIMIT = "graph_node_limit"


class GameTreeLegalityContractError(ValueError):
    def __init__(self, message: str, *, code: LegalityContractCode) -> None:
        super().__init__(message)
        self.code = LegalityContractCode(code)


class LegalityDiagnosticCode(str, Enum):
    INVALID_SETUP_TAG = "invalid_setup_tag"
    MISSING_FEN = "missing_fen"
    FEN_REQUIRES_SETUP = "fen_requires_setup"
    INVALID_FEN = "invalid_fen"
    ILLEGAL_SAN = "illegal_san"
    NONCANONICAL_SAN = "noncanonical_san"
    MOVE_NUMBER_MISMATCH = "move_number_mismatch"
    POSITION_UNAVAILABLE = "position_unavailable"
    RESULT_MISMATCH = "result_mismatch"


class DiagnosticSeverity(str, Enum):
    WARNING = "warning"
    ERROR = "error"


class MoveLinkStatus(str, Enum):
    LEGAL = "legal"
    LEGAL_NONCANONICAL = "legal_noncanonical"
    ILLEGAL = "illegal"
    UNVERIFIED = "unverified"


@dataclass(frozen=True, slots=True)
class VariationStep:
    parent_move_index: int
    variation_index: int

    def __post_init__(self) -> None:
        if type(self.parent_move_index) is not int or self.parent_move_index < 0:
            raise TypeError("parent_move_index must be a non-negative exact integer")
        if type(self.variation_index) is not int or self.variation_index < 0:
            raise TypeError("variation_index must be a non-negative exact integer")


@dataclass(frozen=True, slots=True)
class LegalityLocation:
    branches: tuple[VariationStep, ...] = ()
    move_index: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.branches, tuple) or any(
            not isinstance(step, VariationStep) for step in self.branches
        ):
            raise TypeError("legality branches must be a tuple of VariationStep values")
        if self.move_index is not None and (
            type(self.move_index) is not int or self.move_index < 0
        ):
            raise TypeError("move_index must be a non-negative exact integer or None")

    @property
    def label(self) -> str:
        parts = ["root"]
        for step in self.branches:
            parts.extend(
                (
                    f"move[{step.parent_move_index}]",
                    f"variation[{step.variation_index}]",
                )
            )
        if self.move_index is not None:
            parts.append(f"move[{self.move_index}]")
        return "/".join(parts)


@dataclass(frozen=True, slots=True)
class LegalityDiagnostic:
    code: LegalityDiagnosticCode
    severity: DiagnosticSeverity
    location: LegalityLocation
    message: str
    source_san: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", LegalityDiagnosticCode(self.code))
        object.__setattr__(self, "severity", DiagnosticSeverity(self.severity))
        if not isinstance(self.location, LegalityLocation):
            raise TypeError("diagnostic location must be LegalityLocation")
        if (
            not isinstance(self.message, str)
            or not self.message.strip()
            or "\r" in self.message
            or "\n" in self.message
        ):
            raise ValueError("diagnostic message must be non-empty single-line text")
        if self.source_san is not None and not isinstance(self.source_san, str):
            raise TypeError("diagnostic source_san must be text or None")

    @property
    def summary(self) -> str:
        return f"{self.code.value} at {self.location.label}: {self.message}"


@dataclass(frozen=True, slots=True)
class LinkedMove:
    location: LegalityLocation
    source_san: str
    status: MoveLinkStatus
    before_fen: str | None = None
    after_fen: str | None = None
    canonical_san: str | None = None
    uci: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.location, LegalityLocation) or self.location.move_index is None:
            raise TypeError("linked move location must identify one move")
        if not isinstance(self.source_san, str) or not self.source_san:
            raise ValueError("linked move source_san must be non-empty text")
        object.__setattr__(self, "status", MoveLinkStatus(self.status))
        for name in ("before_fen", "after_fen", "canonical_san", "uci"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value):
                raise TypeError(f"linked move {name} must be non-empty text or None")

        if self.status in {MoveLinkStatus.LEGAL, MoveLinkStatus.LEGAL_NONCANONICAL}:
            if any(
                value is None
                for value in (
                    self.before_fen,
                    self.after_fen,
                    self.canonical_san,
                    self.uci,
                )
            ):
                raise ValueError("legal linked moves require complete position evidence")
        elif self.status is MoveLinkStatus.ILLEGAL:
            if self.before_fen is None or any(
                value is not None
                for value in (self.after_fen, self.canonical_san, self.uci)
            ):
                raise ValueError("illegal linked moves require only the parent position")
        elif any(
            value is not None
            for value in (
                self.before_fen,
                self.after_fen,
                self.canonical_san,
                self.uci,
            )
        ):
            raise ValueError("unverified linked moves cannot claim position evidence")


@dataclass(frozen=True, slots=True)
class GameTreeLegalityReport:
    start_fen: str | None
    final_fen: str | None
    moves: tuple[LinkedMove, ...]
    diagnostics: tuple[LegalityDiagnostic, ...]
    recovery_issue_codes: tuple[PgnRecoveryCode, ...] = ()

    def __post_init__(self) -> None:
        for name in ("start_fen", "final_fen"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value):
                raise TypeError(f"{name} must be non-empty text or None")
        if not isinstance(self.moves, tuple) or any(
            not isinstance(move, LinkedMove) for move in self.moves
        ):
            raise TypeError("report moves must be a tuple of LinkedMove values")
        if not isinstance(self.diagnostics, tuple) or any(
            not isinstance(item, LegalityDiagnostic) for item in self.diagnostics
        ):
            raise TypeError("report diagnostics must be a tuple of LegalityDiagnostic values")
        if not isinstance(self.recovery_issue_codes, tuple):
            raise TypeError("recovery_issue_codes must be a tuple")
        try:
            canonical_codes = tuple(PgnRecoveryCode(code) for code in self.recovery_issue_codes)
        except (TypeError, ValueError) as exc:
            raise TypeError("recovery_issue_codes contain an unsupported value") from exc
        object.__setattr__(self, "recovery_issue_codes", canonical_codes)

    @property
    def complete(self) -> bool:
        return self.start_fen is not None and all(
            move.status is not MoveLinkStatus.UNVERIFIED for move in self.moves
        )

    @property
    def all_moves_legal(self) -> bool:
        return self.complete and all(
            move.status in {MoveLinkStatus.LEGAL, MoveLinkStatus.LEGAL_NONCANONICAL}
            for move in self.moves
        )

    @property
    def has_errors(self) -> bool:
        return any(
            diagnostic.severity is DiagnosticSeverity.ERROR
            for diagnostic in self.diagnostics
        )

    @property
    def canonical(self) -> bool:
        return (
            self.all_moves_legal
            and not self.has_errors
            and not self.recovery_issue_codes
            and all(move.status is MoveLinkStatus.LEGAL for move in self.moves)
        )


def _contract_error(message: str, code: LegalityContractCode) -> None:
    raise GameTreeLegalityContractError(message, code=code)


def _claim_node(state: dict[str, object]) -> None:
    count = int(state["count"]) + 1
    state["count"] = count
    if count > MAX_TREE_NODES:
        _contract_error(
            "GameTree legality traversal exceeds the node safety limit",
            LegalityContractCode.GRAPH_NODE_LIMIT,
        )


def _validate_fen_semantics(board: Board) -> None:
    previous_side = "b" if board.turn == "w" else "w"
    if board.in_check(previous_side):
        raise ValueError("side not to move is already in check")
    if board.ep is None:
        return
    target = board.ep
    if board.board[target] is not None:
        raise ValueError("en-passant target is occupied")
    if board.turn == "w":
        pawn_square, origin_square, pawn = target - 8, target + 8, "p"
    else:
        pawn_square, origin_square, pawn = target + 8, target - 8, "P"
    if board.board[pawn_square] != pawn or board.board[origin_square] is not None:
        raise ValueError("en-passant target lacks a matching double pawn move")
    if board.halfmove != 0:
        raise ValueError("en-passant target requires a zero halfmove clock")


def _starting_board(
    game: PgnGame,
    diagnostics: list[LegalityDiagnostic],
) -> Board | None:
    setup = game.tags.get("SetUp")
    fen = game.tags.get("FEN")
    root = LegalityLocation()

    if setup is not None and setup not in {"0", "1"}:
        diagnostics.append(
            LegalityDiagnostic(
                LegalityDiagnosticCode.INVALID_SETUP_TAG,
                DiagnosticSeverity.ERROR,
                root,
                "SetUp must be exactly 0 or 1",
            )
        )
        return None
    if setup == "1" and fen is None:
        diagnostics.append(
            LegalityDiagnostic(
                LegalityDiagnosticCode.MISSING_FEN,
                DiagnosticSeverity.ERROR,
                root,
                "SetUp 1 requires a FEN tag",
            )
        )
        return None
    if fen is not None and setup != "1":
        diagnostics.append(
            LegalityDiagnostic(
                LegalityDiagnosticCode.FEN_REQUIRES_SETUP,
                DiagnosticSeverity.ERROR,
                root,
                "FEN requires SetUp 1",
            )
        )
        return None

    try:
        board = Board(fen) if fen is not None else Board()
        _validate_fen_semantics(board)
    except (TypeError, ValueError) as exc:
        diagnostics.append(
            LegalityDiagnostic(
                LegalityDiagnosticCode.INVALID_FEN,
                DiagnosticSeverity.ERROR,
                root,
                f"starting FEN is invalid: {exc}",
            )
        )
        return None
    return board


def _uci(move: Move) -> str:
    suffix = move.promotion.lower() if move.promotion else ""
    return f"{sq_name(move.frm)}{sq_name(move.to)}{suffix}"


def _forced_terminal_result(board: Board) -> str | None:
    if board.legal_moves():
        return None
    if board.in_check(board.turn):
        return "0-1" if board.turn == "w" else "1-0"
    return "1/2-1/2"


def _expected_move_number(board: Board) -> str:
    return f"{board.fullmove}." if board.turn == "w" else f"{board.fullmove}..."


def _link_line(
    line: VariationLine,
    start: Board | None,
    *,
    branches: tuple[VariationStep, ...],
    unavailable_reason: str | None,
    state: dict[str, object],
    links: list[LinkedMove],
    diagnostics: list[LegalityDiagnostic],
) -> Board | None:
    depth = len(branches)
    if depth > MAX_VARIATION_DEPTH:
        _contract_error(
            "GameTree legality traversal exceeds the variation depth limit",
            LegalityContractCode.GRAPH_DEPTH_LIMIT,
        )
    if not isinstance(line, VariationLine) or type(line.moves) is not list:
        _contract_error(
            "legality traversal requires VariationLine move lists",
            LegalityContractCode.INVALID_TREE,
        )
    if line.result is not None and (
        not isinstance(line.result, str) or line.result not in RESULTS
    ):
        _contract_error(
            "variation result must be a canonical PGN result or None",
            LegalityContractCode.INVALID_TREE,
        )

    seen = state["seen"]
    active = state["active"]
    assert isinstance(seen, set) and isinstance(active, set)
    identity = id(line)
    if identity in active:
        _contract_error(
            "GameTree contains a cyclic variation reference",
            LegalityContractCode.GRAPH_CYCLE,
        )
    if identity in seen:
        _contract_error(
            "GameTree reuses one VariationLine in multiple locations",
            LegalityContractCode.GRAPH_REUSE,
        )
    seen.add(identity)
    active.add(identity)
    _claim_node(state)

    current = start.clone() if start is not None else None
    blocked_reason = unavailable_reason
    for move_index, node in enumerate(line.moves):
        if not isinstance(node, MoveNode):
            _contract_error(
                "variation move list contains a non-MoveNode value",
                LegalityContractCode.INVALID_TREE,
            )
        node_identity = id(node)
        if node_identity in seen:
            _contract_error(
                "GameTree reuses one MoveNode in multiple locations",
                LegalityContractCode.GRAPH_REUSE,
            )
        seen.add(node_identity)
        _claim_node(state)
        if not isinstance(node.san, str) or not node.san:
            _contract_error(
                "MoveNode SAN must be non-empty text",
                LegalityContractCode.INVALID_TREE,
            )
        if node.move_number is not None and not isinstance(node.move_number, str):
            _contract_error(
                "MoveNode move_number must be text or None",
                LegalityContractCode.INVALID_TREE,
            )
        if type(node.variations) is not list:
            _contract_error(
                "MoveNode variations must be a list",
                LegalityContractCode.INVALID_TREE,
            )

        location = LegalityLocation(branches, move_index)
        before = current.clone() if current is not None else None
        after: Board | None = None
        if before is None:
            links.append(
                LinkedMove(
                    location,
                    node.san,
                    MoveLinkStatus.UNVERIFIED,
                )
            )
            diagnostics.append(
                LegalityDiagnostic(
                    LegalityDiagnosticCode.POSITION_UNAVAILABLE,
                    DiagnosticSeverity.ERROR,
                    location,
                    blocked_reason or "parent position is unavailable",
                    node.san,
                )
            )
        else:
            expected_number = _expected_move_number(before)
            if node.move_number is not None and node.move_number != expected_number:
                diagnostics.append(
                    LegalityDiagnostic(
                        LegalityDiagnosticCode.MOVE_NUMBER_MISMATCH,
                        DiagnosticSeverity.WARNING,
                        location,
                        f"move number {node.move_number!r} does not match {expected_number!r}",
                        node.san,
                    )
                )
            before_fen = before.fen()
            try:
                move = before.parse_move(node.san)
                canonical_san = before.san(move)
            except (IndexError, ValueError):
                links.append(
                    LinkedMove(
                        location,
                        node.san,
                        MoveLinkStatus.ILLEGAL,
                        before_fen=before_fen,
                    )
                )
                diagnostics.append(
                    LegalityDiagnostic(
                        LegalityDiagnosticCode.ILLEGAL_SAN,
                        DiagnosticSeverity.ERROR,
                        location,
                        "SAN does not resolve to exactly one legal move from the parent position",
                        node.san,
                    )
                )
                blocked_reason = f"position after illegal move at {location.label} is unavailable"
            else:
                after = before.clone()
                after.push(move)
                status = (
                    MoveLinkStatus.LEGAL
                    if node.san == canonical_san
                    else MoveLinkStatus.LEGAL_NONCANONICAL
                )
                links.append(
                    LinkedMove(
                        location,
                        node.san,
                        status,
                        before_fen=before_fen,
                        after_fen=after.fen(),
                        canonical_san=canonical_san,
                        uci=_uci(move),
                    )
                )
                if status is MoveLinkStatus.LEGAL_NONCANONICAL:
                    diagnostics.append(
                        LegalityDiagnostic(
                            LegalityDiagnosticCode.NONCANONICAL_SAN,
                            DiagnosticSeverity.WARNING,
                            location,
                            f"canonical SAN is {canonical_san!r}",
                            node.san,
                        )
                    )
                blocked_reason = None

        for variation_index, variation in enumerate(node.variations):
            step = VariationStep(move_index, variation_index)
            _link_line(
                variation,
                before,
                branches=branches + (step,),
                unavailable_reason=(
                    None
                    if before is not None
                    else blocked_reason or "variation parent position is unavailable"
                ),
                state=state,
                links=links,
                diagnostics=diagnostics,
            )
        current = after

    if current is not None and line.result is not None:
        forced_result = _forced_terminal_result(current)
        if forced_result is not None and line.result != forced_result:
            diagnostics.append(
                LegalityDiagnostic(
                    LegalityDiagnosticCode.RESULT_MISMATCH,
                    DiagnosticSeverity.ERROR,
                    LegalityLocation(branches),
                    f"terminal position requires result {forced_result!r}, not {line.result!r}",
                )
            )

    active.remove(identity)
    return current


def link_game_legality(game: PgnGame) -> GameTreeLegalityReport:
    """Link a structural GameTree to positions without mutating source data."""

    if not isinstance(game, PgnGame):
        _contract_error(
            "link_game_legality requires a PgnGame",
            LegalityContractCode.INVALID_GAME,
        )
    if type(game.tags) is not dict or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in game.tags.items()
    ):
        _contract_error(
            "PgnGame tags must be a text dictionary",
            LegalityContractCode.INVALID_GAME,
        )
    if type(game.recovery_issues) is not list or any(
        not isinstance(issue, PgnRecoveryIssue) for issue in game.recovery_issues
    ):
        _contract_error(
            "PgnGame recovery_issues must contain PgnRecoveryIssue values",
            LegalityContractCode.INVALID_GAME,
        )

    diagnostics: list[LegalityDiagnostic] = []
    links: list[LinkedMove] = []
    start = _starting_board(game, diagnostics)
    state: dict[str, object] = {"seen": set(), "active": set(), "count": 0}
    final = _link_line(
        game.line,
        start,
        branches=(),
        unavailable_reason=(None if start is not None else "starting position is unavailable"),
        state=state,
        links=links,
        diagnostics=diagnostics,
    )
    return GameTreeLegalityReport(
        start_fen=start.fen() if start is not None else None,
        final_fen=final.fen() if final is not None else None,
        moves=tuple(links),
        diagnostics=tuple(diagnostics),
        recovery_issue_codes=tuple(issue.code for issue in game.recovery_issues),
    )
