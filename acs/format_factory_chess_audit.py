from __future__ import annotations

"""Section 54.4: source-preserving chess structure audit for one semantic book.

The canonical BookDocument, BookGameContent, Board and GameTree legality walker
own all interpretation. This is NOT verification against scanned book pages,
OCR, an edition's text, external sources, or an AI model. A structurally legal
position/game must never be advertised as proven faithful to its source.
"""

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json

from .bookdocument import (
    BookDocument, Diagram, Exercise, Game, Position, VariationTree,
)
from .book_game_content import (
    BookGameContentError, resolve_book_game, resolve_book_variation,
)
from .chesscore import Board
from .gametree_legality import validate_game_legality


class FactoryChessAuditError(ValueError):
    """An audit could not be completed within the verified input boundary."""


@dataclass(frozen=True, slots=True)
class FactoryChessBlockResult:
    block_index: int
    kind: str
    status: str
    legal_moves: int
    issue_codes: tuple[str, ...]
    source_verified: bool = False


@dataclass(frozen=True, slots=True)
class FactoryChessAudit:
    book_sha256: str
    chess_blocks: int
    legal_chess_blocks: int
    invalid_chess_blocks: int
    blocks: tuple[FactoryChessBlockResult, ...]
    structure_complete: bool
    source_verified: bool = False
    ready_for_publication: bool = False


def audit_factory_book_chess(
    document: BookDocument, *, max_blocks: int = 4096,
) -> FactoryChessAudit:
    """Run the existing canonical chess validators on a detached Book snapshot.

    Books larger than the bounded batch must be split by the caller; no partial
    result is silently labeled as a full-book audit. Never call Stockfish as a
    substitute for the independent source-page fidelity qualification.
    """
    if type(document) is not BookDocument:
        raise FactoryChessAuditError("Canonical BookDocument required")
    if type(max_blocks) is not int or not 1 <= max_blocks <= 4096:
        raise FactoryChessAuditError("Auditor batch size is invalid")
    try:
        payload = document.as_dict()
        blocks = payload["blocks"]
        if len(blocks) > max_blocks:
            raise FactoryChessAuditError("Book exceeds selected audit batch; select a fragment")
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        source_digest = sha256(encoded).hexdigest()
        snapshot = BookDocument.from_dict(payload)
    except FactoryChessAuditError:
        raise
    except (ValueError, TypeError, UnicodeError, OverflowError) as exc:
        raise FactoryChessAuditError("Book content is not canonically valid") from exc

    results: list[FactoryChessBlockResult] = []
    chess_count = 0
    legal_count = 0
    for index, block in enumerate(snapshot.blocks):
        kind = block.kind
        if not isinstance(block, (Game, VariationTree, Position, Diagram, Exercise)):
            continue
        chess_count += 1
        codes: tuple[str, ...] = ()
        legal_moves = 0
        try:
            if isinstance(block, (Position, Diagram, Exercise)):
                # Position, Diagram, and Exercise all carry authorial FEN; only
                # canonical Board can determine whether it is structurally legal.
                Board(block.fen)
            else:
                if isinstance(block, Game):
                    resolved = resolve_book_game(block)
                    game = resolved.game
                    warnings = tuple(resolved.warnings) + tuple(game.warnings)
                else:
                    resolved = resolve_book_variation(block)
                    warnings = tuple(resolved.warnings) + tuple(resolved.game.warnings)
                    # Match the canonical BookBoardWorkflow's detached root
                    # binding; the semantic variation's starting FEN wins only
                    # after resolve_book_variation proves source-tag consistency.
                    game = deepcopy(resolved.game)
                    game.tags = dict(game.tags)
                    game.tags["SetUp"] = "1"
                    game.tags["FEN"] = Board(resolved.root_fen).fen()
                report = validate_game_legality(game)
                legal_moves = report.legal_move_count
                codes = tuple(issue.code.value for issue in report.issues)
                if warnings or not report.complete or report.start_fen is None:
                    codes = codes + ("RECOVERED_OR_INCOMPLETE_GAME",)
                if codes:
                    raise FactoryChessAuditError("Canonical chess legality is not proven")
            status = "CHESS_LEGAL_ONLY"
            legal_count += 1
        except FactoryChessAuditError:
            status = "INVALID_CHESS_STRUCTURE"
        except (BookGameContentError, TypeError, ValueError, RecursionError, KeyError, AttributeError):
            status = "INVALID_CHESS_STRUCTURE"
            codes = codes + ("CANONICAL_BLOCK_REJECTED",)

        results.append(FactoryChessBlockResult(
            block_index=index,
            kind=kind,
            status=status,
            legal_moves=legal_moves,
            issue_codes=codes,
        ))
    return FactoryChessAudit(
        book_sha256=source_digest,
        chess_blocks=chess_count,
        legal_chess_blocks=legal_count,
        invalid_chess_blocks=chess_count - legal_count,
        blocks=tuple(results),
        structure_complete=(legal_count == chess_count),
        source_verified=False,
        ready_for_publication=False,
    )
