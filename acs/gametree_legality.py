from __future__ import annotations

"""Non-destructive chess-legality projection for the canonical structural GameTree.

The PGN parser deliberately preserves damaged historical source structure.  This
module links that structure to :class:`acs.chesscore.Board` without rewriting or
flattening it.  Every RAV is evaluated from the position *before* its owning
move, matching PGN recursive-annotation semantics.  An illegal move stops only
that line; sibling variations with a known branch position remain independently
verifiable.
"""

from dataclasses import dataclass
from enum import Enum

from .chesscore import Board
from .gametree import MAX_TREE_NODES, MAX_VARIATION_DEPTH, MoveNode, PgnGame, VariationLine
from .gametree_navigation import MoveAddress, ROOT_PATH, VariationPath, VariationStep


class GameTreeLegalityCode(str, Enum):
    INVALID_GAME = "invalid_game"
    INVALID_START_POSITION = "invalid_start_position"
    FEN_WITHOUT_SETUP = "fen_without_setup"
    MOVE_NUMBER_MISMATCH = "move_number_mismatch"
    ILLEGAL_MOVE = "illegal_move"
    GRAPH_CYCLE = "graph_cycle"
    GRAPH_REUSE = "graph_reuse"
    GRAPH_DEPTH_LIMIT = "graph_depth_limit"
    GRAPH_NODE_LIMIT = "graph_node_limit"


@dataclass(frozen=True, slots=True)
class LegalityIssue:
    code: GameTreeLegalityCode
    message: str
    address: MoveAddress | None = None
    san: str | None = None


@dataclass(frozen=True, slots=True)
class LegalMoveProjection:
    address: MoveAddress
    san_source: str
    san_canonical: str
    fen_before: str
    fen_after: str


@dataclass(frozen=True, slots=True)
class GameTreeLegalityReport:
    start_fen: str | None
    moves: tuple[LegalMoveProjection, ...]
    issues: tuple[LegalityIssue, ...]
    complete: bool

    @property
    def legal_move_count(self) -> int:
        return len(self.moves)


def _start_board(game: PgnGame) -> tuple[Board | None, list[LegalityIssue]]:
    issues: list[LegalityIssue] = []
    if type(game.tags) is not dict:
        return None, [
            LegalityIssue(
                GameTreeLegalityCode.INVALID_GAME,
                "game tags must be a dictionary",
            )
        ]

    setup = game.tags.get("SetUp")
    fen = game.tags.get("FEN")
    if setup == "1":
        if not isinstance(fen, str) or not fen.strip():
            return None, [
                LegalityIssue(
                    GameTreeLegalityCode.INVALID_START_POSITION,
                    "SetUp=1 requires a non-empty FEN tag",
                )
            ]
        try:
            return Board(fen), issues
        except Exception as exc:
            return None, [
                LegalityIssue(
                    GameTreeLegalityCode.INVALID_START_POSITION,
                    f"invalid SetUp/FEN start position: {exc}",
                )
            ]

    if fen is not None:
        issues.append(
            LegalityIssue(
                GameTreeLegalityCode.FEN_WITHOUT_SETUP,
                "FEN tag is preserved but not applied because SetUp is not 1",
            )
        )
    try:
        return Board(Board.START), issues
    except Exception as exc:  # defensive: canonical START must always be valid
        return None, [
            LegalityIssue(
                GameTreeLegalityCode.INVALID_START_POSITION,
                f"canonical start position is invalid: {exc}",
            )
        ]


def _expected_move_number(board: Board) -> str:
    return f"{board.fullmove}." if board.turn == "w" else f"{board.fullmove}..."


def validate_game_legality(game: PgnGame) -> GameTreeLegalityReport:
    """Project one structural PGN game through canonical chess legality.

    The input graph is never mutated.  Legal moves are applied only to private
    ``Board`` clones.  A bad SAN stops continuation of that one line because the
    following position is unknowable, but variations attached to that move are
    still checked from the known pre-move branch position.
    """

    if not isinstance(game, PgnGame) or not isinstance(game.line, VariationLine):
        issue = LegalityIssue(
            GameTreeLegalityCode.INVALID_GAME,
            "legality projection requires a PgnGame with a VariationLine root",
        )
        return GameTreeLegalityReport(None, (), (issue,), False)

    board, start_issues = _start_board(game)
    if board is None:
        return GameTreeLegalityReport(None, (), tuple(start_issues), False)

    start_fen = board.fen()
    projections: list[LegalMoveProjection] = []
    issues = list(start_issues)
    seen_lines: set[int] = set()
    seen_moves: set[int] = set()
    node_count = 0
    complete = True

    def claim() -> bool:
        nonlocal node_count, complete
        node_count += 1
        if node_count > MAX_TREE_NODES:
            issues.append(
                LegalityIssue(
                    GameTreeLegalityCode.GRAPH_NODE_LIMIT,
                    "GameTree legality projection exceeded the node safety limit",
                )
            )
            complete = False
            return False
        return True

    def walk(line: VariationLine, path: VariationPath, line_board: Board, depth: int) -> None:
        nonlocal complete
        if depth > MAX_VARIATION_DEPTH:
            issues.append(
                LegalityIssue(
                    GameTreeLegalityCode.GRAPH_DEPTH_LIMIT,
                    "GameTree legality projection exceeded the variation depth limit",
                )
            )
            complete = False
            return
        line_id = id(line)
        if line_id in seen_lines:
            issues.append(
                LegalityIssue(
                    GameTreeLegalityCode.GRAPH_REUSE,
                    "GameTree reuses or cycles a VariationLine during legality projection",
                )
            )
            complete = False
            return
        seen_lines.add(line_id)
        if not claim():
            return
        if type(line.moves) is not list:
            issues.append(
                LegalityIssue(
                    GameTreeLegalityCode.INVALID_GAME,
                    "variation moves must be a list",
                )
            )
            complete = False
            return

        current = line_board.clone()
        for move_index, node in enumerate(line.moves):
            if not isinstance(node, MoveNode):
                issues.append(
                    LegalityIssue(
                        GameTreeLegalityCode.INVALID_GAME,
                        "variation contains a non-MoveNode value",
                    )
                )
                complete = False
                return
            node_id = id(node)
            if node_id in seen_moves:
                issues.append(
                    LegalityIssue(
                        GameTreeLegalityCode.GRAPH_REUSE,
                        "GameTree reuses one MoveNode in multiple locations",
                        address=MoveAddress(path, move_index),
                    )
                )
                complete = False
                return
            seen_moves.add(node_id)
            if not claim():
                return

            address = MoveAddress(path, move_index)
            before = current.clone()
            if node.move_number is not None:
                expected = _expected_move_number(before)
                if node.move_number != expected:
                    issues.append(
                        LegalityIssue(
                            GameTreeLegalityCode.MOVE_NUMBER_MISMATCH,
                            f"move number {node.move_number!r} does not match expected {expected!r}",
                            address=address,
                            san=node.san,
                        )
                    )

            legal = True
            try:
                canonical_san = current.push_text(node.san)
            except Exception as exc:
                legal = False
                canonical_san = ""
                issues.append(
                    LegalityIssue(
                        GameTreeLegalityCode.ILLEGAL_MOVE,
                        f"illegal or unrecognized move {node.san!r}: {exc}",
                        address=address,
                        san=node.san,
                    )
                )
                complete = False

            if type(node.variations) is not list:
                issues.append(
                    LegalityIssue(
                        GameTreeLegalityCode.INVALID_GAME,
                        "move variations must be a list",
                        address=address,
                        san=node.san,
                    )
                )
                complete = False
            else:
                for variation_index, child in enumerate(node.variations):
                    if not isinstance(child, VariationLine):
                        issues.append(
                            LegalityIssue(
                                GameTreeLegalityCode.INVALID_GAME,
                                "move variations must contain VariationLine values",
                                address=address,
                                san=node.san,
                            )
                        )
                        complete = False
                        continue
                    child_path = path + (VariationStep(move_index, variation_index),)
                    walk(child, child_path, before, depth + 1)

            if not legal:
                return
            projections.append(
                LegalMoveProjection(
                    address=address,
                    san_source=node.san,
                    san_canonical=canonical_san,
                    fen_before=before.fen(),
                    fen_after=current.fen(),
                )
            )

    walk(game.line, ROOT_PATH, board, 0)
    return GameTreeLegalityReport(
        start_fen=start_fen,
        moves=tuple(projections),
        issues=tuple(issues),
        complete=complete,
    )
