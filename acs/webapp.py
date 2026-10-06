from __future__ import annotations

"""Accessible WebView2 presentation layer for Accessible Chess.

The 0.3.x Tkinter surface failed the first real NVDA acceptance test. This
module keeps the chess core in Python but renders the user-facing document as
semantic HTML inside Edge/WebView2 on Windows. The HTML document is intended
to be consumed by NVDA browse/focus mode rather than by a self-voicing GUI.
"""

from pathlib import Path
import copy
import re
import sys
from typing import Any

from .chesscore import Board, parse_sq, sq_name, color_of
from .history import HistoryError, ReviewHistory
from .input_limits import MAX_FEN_CHARS, MAX_SQUARE_TEXT_CHARS
from .move_entry import MAX_MOVE_ENTRY_CHARS
from .notation import format_accessible_compact_san, format_san
from .position_editor import PositionState, PositionValidationError
from .position_text import parse_position_text
from .ui_review_adapter import ReviewPresentationAdapter

VERSION = "0.4.0-dev3"

PIECE_UK = {
    "K": "білий король", "Q": "білий ферзь", "R": "біла тура",
    "B": "білий слон", "N": "білий кінь", "P": "білий пішак",
    "k": "чорний король", "q": "чорний ферзь", "r": "чорна тура",
    "b": "чорний слон", "n": "чорний кінь", "p": "чорний пішак",
}
PIECE_EN = {
    "K": "white king", "Q": "white queen", "R": "white rook",
    "B": "white bishop", "N": "white knight", "P": "white pawn",
    "k": "black king", "q": "black queen", "r": "black rook",
    "b": "black bishop", "n": "black knight", "p": "black pawn",
}
TYPE_UK = {"K": "король", "Q": "ферзь", "R": "тура", "B": "слон", "N": "кінь", "P": "пішак"}
TYPE_EN = {"K": "king", "Q": "queen", "R": "rook", "B": "bishop", "N": "knight", "P": "pawn"}


def _asset_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parent.parent


def _spaced_square(name: str) -> str:
    return f"{name[0]} {name[1]}"


class AccessibleChessAPI:
    def __init__(self, lang: str = "uk") -> None:
        self.lang = lang if type(lang) is str and lang in ("uk", "en") else "uk"
        self.board = Board()
        self.start_fen = self.board.fen()
        self.sans: list[str] = []
        self.move_sides: list[str] = []
        self.redo_meta: list[tuple[str, str]] = []
        self.selected_source: int | None = None
        self.announcement = self._t("ready")
        self.mode = "analysis"
        self.engine_enabled = False
        self.review_history = ReviewHistory(self.start_fen)
        self.review_adapter = ReviewPresentationAdapter(self.review_history, language=self.lang)
        self.live_history_node = self.review_history.cursor_node_id

    @property
    def review_cursor(self) -> int:
        """Compatibility projection; ReviewHistory remains the cursor owner."""
        return self.review_adapter.current().ply

    def _t(self, key: str) -> str:
        uk = {
            "ready": "Готово. Документ доступності завантажено.",
            "white_turn": "Хід білих", "black_turn": "Хід чорних",
            "no_moves": "Ходів ще немає", "no_last": "Останнього ходу немає",
            "selected": "вибрано", "illegal": "Не вдалося виконати хід",
            "undo_none": "Немає ходу для скасування", "redo_none": "Немає ходу для повторення",
            "setup_incomplete": "Редактор позиції. Додайте рівно по одному білому і чорному королю.",
            "move_text_type": "Текст ходу має бути текстовим значенням.",
            "move_text_too_long": "Текст ходу занадто довгий.",
            "move_invalid": "Не вдалося виконати хід. Перевірте запис і позицію.",
            "square_invalid": "Неправильне поле.",
            "fen_text_type": "FEN має бути текстовим значенням.",
            "fen_text_too_long": "FEN занадто довгий.",
            "fen_invalid": "Некоректний FEN.",
            "position_invalid": "Некоректна позиція.",
            "position_history_failed": "Не вдалося підготувати історію нової позиції.",
            "fen_history_failed": "Не вдалося підготувати історію FEN-позиції.",
            "editor_history_failed": "Не вдалося підготувати історію зміненої позиції.",
            "language_change_failed": "Не вдалося змінити мову інтерфейсу.",
            "move_history_failed": "Не вдалося синхронізувати дошку та історію ходів.",
            "review_position_failed": "Не вдалося підготувати вибрану позицію історії.",
            "review_start": "Початкова позиція.",
            "review_end": "Кінець історії.",
            "review_before_move": "Спочатку поверніться в кінець історії, щоб зробити новий хід.",
            "review_invalid": "Такої позиції в історії немає.",
        }
        en = {
            "ready": "Ready. Accessible document loaded.",
            "white_turn": "White to move", "black_turn": "Black to move",
            "no_moves": "No moves yet", "no_last": "No last move",
            "selected": "selected", "illegal": "Could not make the move",
            "undo_none": "No move to undo", "redo_none": "No move to redo",
            "setup_incomplete": "Position editor. Add exactly one white king and one black king.",
            "move_text_type": "Move text must be a text value.",
            "move_text_too_long": "Move text is too long.",
            "move_invalid": "Could not make the move. Check the notation and position.",
            "square_invalid": "Invalid square.",
            "fen_text_type": "FEN must be a text value.",
            "fen_text_too_long": "FEN is too long.",
            "fen_invalid": "Invalid FEN.",
            "position_invalid": "Invalid position.",
            "position_history_failed": "Could not prepare history for the new position.",
            "fen_history_failed": "Could not prepare history for the FEN position.",
            "editor_history_failed": "Could not prepare history for the edited position.",
            "language_change_failed": "Could not change interface language.",
            "move_history_failed": "Could not synchronize the board and move history.",
            "review_position_failed": "Could not prepare the selected history position.",
            "review_start": "Initial position.",
            "review_end": "End of history.",
            "review_before_move": "Return to the end of history before playing a new move.",
            "review_invalid": "That historical position does not exist.",
        }
        return (uk if self.lang == "uk" else en).get(key, key)

    def _piece_name(self, p: str) -> str:
        return (PIECE_UK if self.lang == "uk" else PIECE_EN)[p]

    def _display_review(self):
        return self.review_adapter.current()

    def _display_board(self) -> Board:
        view = self._display_review()
        if view.node_id == self.live_history_node:
            return self.board
        return Board(view.fen)

    def _position_complete(self, board: Board | None = None) -> bool:
        b = board or self._display_board()
        return b.board.count("K") == 1 and b.board.count("k") == 1

    def _position_playable(self, board: Board | None = None) -> bool:
        """Ask the canonical Board FEN authority whether gameplay may start."""

        b = board or self._display_board()
        if not self._position_complete(b):
            return False
        try:
            Board(b.fen())
        except Exception:
            return False
        return True

    def square_label(self, square: int | str, board: Board | None = None) -> str:
        b = board or self._display_board()
        # Use the canonical exact-int/exact-text square boundary for both forms.
        # Coercing arbitrary values with int() can execute provider code and also
        # turns booleans/floats/negative indices into the wrong spoken square.
        s = parse_sq(square)
        coord = _spaced_square(sq_name(s))
        p = b.board[s]
        return coord if not p else f"{coord}, {self._piece_name(p)}"

    def _pieces_text(self, color: str, board: Board | None = None) -> str:
        b = board or self._display_board()
        names = TYPE_UK if self.lang == "uk" else TYPE_EN
        lines: list[str] = []
        for typ in "KQRBNP":
            squares = [_spaced_square(sq_name(i)) for i, p in enumerate(b.board)
                       if p and p.upper() == typ and color_of(p) == color]
            if squares:
                lines.append(f"{names[typ]}: {', '.join(squares)}")
        return "; ".join(lines) if lines else ("фігур немає" if self.lang == "uk" else "no pieces")

    def _visible_ply_count(self) -> int:
        return min(self.review_adapter.current().ply, len(self.sans))

    def _moves_text(self) -> str:
        count = self._visible_ply_count()
        if count == 0:
            return self._t("no_moves")
        sans = self.sans[:count]
        sides = self.move_sides[:count]
        out: list[str] = []
        move_no = 1
        i = 0
        while i < len(sans):
            side = sides[i]
            if side == "w":
                white = format_accessible_compact_san(sans[i], self.lang)
                if i + 1 < len(sans) and sides[i + 1] == "b":
                    black = format_accessible_compact_san(sans[i + 1], self.lang)
                    out.append(f"{move_no}. {white}, {black}.")
                    i += 2
                else:
                    out.append(f"{move_no}. {white}.")
                    i += 1
                move_no += 1
            else:
                out.append(f"{move_no}... {format_accessible_compact_san(sans[i], self.lang)}.")
                move_no += 1
                i += 1
        return "\n".join(out)

    def _history_items(self) -> list[dict[str, Any]]:
        """Project the immutable live line as a selectable review move list.

        Arrow-key browsing belongs to presentation; each item carries only the
        canonical ply target that go_to_move already validates before review
        publication. Review selection never mutates the live Board.
        """
        try:
            lineage = self._live_line_nodes()
        except Exception:
            return []
        current_node = self.review_history.cursor_node_id
        items: list[dict[str, Any]] = []
        for ply, (san, side) in enumerate(
            zip(self.sans, self.move_sides, strict=True),
            start=1,
        ):
            move_number = (ply + 1) // 2
            prefix = f"{move_number}." if side == "w" else f"{move_number}..."
            items.append(
                {
                    "ply": ply,
                    "label": f"{prefix} {format_accessible_compact_san(san, self.lang)}",
                    "selected": ply < len(lineage) and lineage[ply] == current_node,
                    "live": ply < len(lineage) and lineage[ply] == self.live_history_node,
                }
            )
        return items

    def _game_status(self, board: Board | None = None) -> str:
        b = board or self._display_board()
        turn_text = self._t("white_turn") if b.turn == "w" else self._t("black_turn")
        if not self._position_complete(b):
            return f"{self._t('setup_incomplete')} {turn_text}"
        if not self._position_playable(b):
            return f"{self._t('position_invalid')} {turn_text}"
        legal = b.legal_moves()
        if legal:
            if b.in_check(b.turn):
                return turn_text + (". Шах." if self.lang == "uk" else ". Check.")
            return turn_text
        if b.in_check(b.turn):
            return ("Мат. " if self.lang == "uk" else "Checkmate. ") + turn_text
        return "Пат." if self.lang == "uk" else "Stalemate."

    def _board_cells(self, board: Board | None = None) -> list[dict[str, Any]]:
        b = board or self._display_board()
        cells = []
        reviewing = not self._at_history_end()
        for rank in range(7, -1, -1):
            for file in range(8):
                sq = rank * 8 + file
                cells.append({
                    "square": sq_name(sq),
                    "label": self.square_label(sq, b),
                    "occupied": bool(b.board[sq]),
                    "selected": (not reviewing) and sq == self.selected_source,
                })
        return cells

    def _prepare_root_state(
        self,
        candidate_board: Board,
        *,
        language: str | None = None,
    ) -> tuple[str, ReviewHistory, ReviewPresentationAdapter, int]:
        """Build a complete root/history presentation before publishing it."""
        candidate_board.undo_stack = []
        candidate_board.redo_stack = []
        candidate_board.last_move = None
        candidate_start_fen = candidate_board.fen()
        candidate_history = ReviewHistory(candidate_start_fen)
        candidate_adapter = ReviewPresentationAdapter(
            candidate_history,
            language=self.lang if language is None else language,
        )
        return (
            candidate_start_fen,
            candidate_history,
            candidate_adapter,
            candidate_history.cursor_node_id,
        )

    def _publish_root_state(
        self,
        candidate_board: Board,
        prepared: tuple[str, ReviewHistory, ReviewPresentationAdapter, int],
    ) -> None:
        candidate_start_fen, candidate_history, candidate_adapter, candidate_live_node = prepared
        self.board = candidate_board
        self.start_fen = candidate_start_fen
        self.sans = []
        self.move_sides = []
        self.redo_meta = []
        self.selected_source = None
        self.review_history = candidate_history
        self.review_adapter = candidate_adapter
        self.live_history_node = candidate_live_node

    def _reset_history(self) -> None:
        # Resetting history is itself transactional. The live board and
        # presentation remain untouched if history/presenter construction fails.
        candidate_board = copy.deepcopy(self.board)
        prepared = self._prepare_root_state(candidate_board)
        self._publish_root_state(candidate_board, prepared)

    def _clone_live_transaction(self) -> tuple[Board, ReviewHistory]:
        """Clone the mutable Board/history owners without publishing either."""
        candidate_board = copy.deepcopy(self.board)
        candidate_history = ReviewHistory.from_tree(self.review_history.export_tree())
        return candidate_board, candidate_history

    def _prepare_live_presentation(
        self,
        candidate_board: Board,
        candidate_history: ReviewHistory,
    ) -> tuple[ReviewPresentationAdapter, int]:
        """Validate one candidate Board/history pair before publication."""
        candidate_adapter = ReviewPresentationAdapter(
            candidate_history,
            language=self.lang,
        )
        view = candidate_adapter.current()
        if view.fen != candidate_board.fen():
            raise RuntimeError("candidate board/history FEN mismatch")
        return candidate_adapter, candidate_history.cursor_node_id

    def _publish_live_transaction(
        self,
        candidate_board: Board,
        candidate_history: ReviewHistory,
        candidate_adapter: ReviewPresentationAdapter,
        candidate_live_node: int,
        *,
        sans: list[str],
        move_sides: list[str],
        redo_meta: list[tuple[str, str]],
    ) -> None:
        self.board = candidate_board
        self.sans = sans
        self.move_sides = move_sides
        self.redo_meta = redo_meta
        self.selected_source = None
        self.review_history = candidate_history
        self.review_adapter = candidate_adapter
        self.live_history_node = candidate_live_node

    def _at_history_end(self) -> bool:
        return self.review_history.cursor_node_id == self.live_history_node

    def _clone_review_transaction(
        self,
    ) -> tuple[ReviewHistory, ReviewPresentationAdapter]:
        candidate_history = ReviewHistory.from_tree(self.review_history.export_tree())
        candidate_adapter = ReviewPresentationAdapter(
            candidate_history,
            language=self.lang,
        )
        return candidate_history, candidate_adapter

    def _validate_review_view(self, view: Any) -> None:
        # The live node must remain an exact projection of the canonical live
        # Board. Historical nodes must at least be renderable by chesscore
        # before the review cursor becomes externally visible.
        if view.node_id == self.live_history_node:
            if view.fen != self.board.fen():
                raise RuntimeError("live review node does not match live board")
            return
        Board(view.fen)

    def _publish_review_transaction(
        self,
        candidate_history: ReviewHistory,
        candidate_adapter: ReviewPresentationAdapter,
    ) -> None:
        self.review_history = candidate_history
        self.review_adapter = candidate_adapter
        self.selected_source = None

    def _live_line_nodes(
        self,
        history: ReviewHistory | None = None,
    ) -> list[int]:
        source = self.review_history if history is None else history
        records = source.tree_nodes()
        by_id = {record.node_id: record for record in records}
        lineage: list[int] = []
        current: int | None = self.live_history_node
        while current is not None:
            lineage.append(current)
            current = by_id[current].parent_id
        lineage.reverse()
        return lineage

    def review_previous(self) -> dict[str, Any]:
        try:
            candidate_history, candidate_adapter = self._clone_review_transaction()
            result = candidate_adapter.previous()
            if not result.ok:
                return self._error(result.announcement)
            self._validate_review_view(result.view)
        except Exception:
            return self._error(self._t("review_position_failed"))
        self._publish_review_transaction(candidate_history, candidate_adapter)
        return self._ok(result.announcement)

    def review_next(self) -> dict[str, Any]:
        if self._at_history_end():
            return self._error(self._t("review_end"))
        try:
            candidate_history, candidate_adapter = self._clone_review_transaction()
            result = candidate_adapter.next()
            if not result.ok:
                return self._error(result.announcement)
            if result.view.node_id not in self._live_line_nodes(candidate_history):
                candidate_history.select_node(self.live_history_node)
                live_view = candidate_adapter.current()
                self._validate_review_view(live_view)
                self._publish_review_transaction(candidate_history, candidate_adapter)
                return self._error(self._t("review_invalid"))
            self._validate_review_view(result.view)
        except Exception:
            return self._error(self._t("review_position_failed"))
        self._publish_review_transaction(candidate_history, candidate_adapter)
        return self._ok(result.announcement)

    def _select_review_node(self, node_id: int) -> dict[str, Any]:
        try:
            candidate_history, candidate_adapter = self._clone_review_transaction()
            result = candidate_adapter.select_node(node_id)
            if not result.ok:
                return self._error(result.announcement)
            self._validate_review_view(result.view)
        except Exception:
            return self._error(self._t("review_position_failed"))
        self._publish_review_transaction(candidate_history, candidate_adapter)
        return self._ok(result.announcement)

    def go_to_move(self, target: str) -> dict[str, Any]:
        if type(target) is not str:
            return self._error(self._t("review_invalid"))
        raw = target.strip().lower()
        try:
            lineage = self._live_line_nodes()
        except Exception:
            return self._error(self._t("review_position_failed"))
        if raw in ("0", "start"):
            return self._select_review_node(lineage[0])
        if raw == "end":
            return self._select_review_node(self.live_history_node)
        try:
            ply = self.review_history.parse_target(raw)
        except HistoryError:
            return self._error(self._t("review_invalid"))
        if ply < 0 or ply >= len(lineage):
            return self._error(self._t("review_invalid"))
        return self._select_review_node(lineage[ply])

    def get_state(self) -> dict[str, Any]:
        display_view = self._display_review()
        display_board = self._display_board()
        visible = self._visible_ply_count()
        last = (
            format_accessible_compact_san(self.sans[visible - 1], self.lang)
            if visible else self._t("no_last")
        )
        status = self._game_status(display_board)
        engine_status = (
            "Stockfish увімкнено." if self.lang == "uk" else "Stockfish enabled."
        ) if self.engine_enabled else (
            "Stockfish вимкнено." if self.lang == "uk" else "Stockfish disabled."
        )
        try:
            editor_state = PositionState.from_fen(display_view.fen)
            editor_projection = {
                "turn": editor_state.turn,
                "castling": editor_state.castling,
                "enPassant": editor_state.en_passant,
                "halfmove": editor_state.halfmove,
                "fullmove": editor_state.fullmove,
                "editable": self._at_history_end(),
            }
        except PositionValidationError:
            editor_projection = {
                "turn": display_board.turn,
                "castling": display_board.castling or "-",
                "enPassant": "-" if display_board.ep is None else sq_name(display_board.ep),
                "halfmove": display_board.halfmove,
                "fullmove": display_board.fullmove,
                "editable": self._at_history_end(),
            }

        return {
            "version": VERSION, "lang": self.lang, "mode": self.mode,
            "gameInfo": status,
            "moves": self._moves_text(),
            "whitePieces": self._pieces_text("w", display_board),
            "blackPieces": self._pieces_text("b", display_board),
            "gameStatus": status, "lastMove": last, "announcement": self.announcement,
            "fen": display_view.fen, "board": self._board_cells(display_board),
            "positionEditor": editor_projection,
            "selectedSquare": (
                sq_name(self.selected_source)
                if self.selected_source is not None and self._at_history_end() else None
            ),
            "engineEnabled": self.engine_enabled, "engineStatus": engine_status,
            "positionComplete": self._position_playable(display_board),
            "reviewCursor": display_view.ply, "historyLength": len(self.sans),
            "historyItems": self._history_items(),
            "reviewStatus": display_view.status, "atHistoryEnd": self._at_history_end(),
        }

    def _ok(self, message: str) -> dict[str, Any]:
        self.announcement = message
        state = self.get_state()
        state["ok"] = True
        return state

    def _error(self, message: str) -> dict[str, Any]:
        self.announcement = message
        state = self.get_state()
        state["ok"] = False
        return state

    def new_game(self) -> dict[str, Any]:
        try:
            candidate_board = Board()
            prepared = self._prepare_root_state(candidate_board)
        except Exception:
            return self._error(self._t("editor_history_failed"))
        self._publish_root_state(candidate_board, prepared)
        return self._ok("Стандартну позицію встановлено." if self.lang == "uk" else "Standard position loaded.")

    def clear_board(self) -> dict[str, Any]:
        try:
            candidate_board = copy.deepcopy(self.board)
            candidate_board.board = [None] * 64
            candidate_board.turn = "w"
            candidate_board.castling = ""
            candidate_board.ep = None
            candidate_board.halfmove = 0
            candidate_board.fullmove = 1
            prepared = self._prepare_root_state(candidate_board)
        except Exception:
            return self._error(self._t("editor_history_failed"))
        self._publish_root_state(candidate_board, prepared)
        return self._ok("Дошку очищено. Введіть позицію в редакторі." if self.lang == "uk"
                        else "Board cleared. Enter a position in the editor.")

    def _position_state_from_live_board(self) -> PositionState:
        return PositionState.from_fen(self.board.fen())

    def _commit_position_editor_state(self, state: PositionState, message_uk: str, message_en: str) -> dict[str, Any]:
        if not self._at_history_end():
            return self._error(self._t("review_before_move"))
        try:
            if len(state.to_fen()) > MAX_FEN_CHARS:
                return self._error(self._t("fen_text_too_long"))
            candidate_board = copy.deepcopy(self.board)
            candidate_board.board = list(state.pieces)
            candidate_board.turn = state.turn
            candidate_board.castling = "" if state.castling == "-" else state.castling
            candidate_board.ep = None if state.en_passant == "-" else parse_sq(state.en_passant)
            candidate_board.halfmove = state.halfmove
            candidate_board.fullmove = state.fullmove
            candidate_board.undo_stack = []
            candidate_board.redo_stack = []
            candidate_board.last_move = None
            prepared = self._prepare_root_state(candidate_board)
        except Exception:
            return self._error(self._t("editor_history_failed"))
        self._publish_root_state(candidate_board, prepared)
        return self._ok(message_uk if self.lang == "uk" else message_en)

    def edit_position_piece(self, square: str, piece: str) -> dict[str, Any]:
        if type(square) is not str or type(piece) is not str:
            return self._error("Неправильне поле або фігура." if self.lang == "uk" else "Invalid square or piece.")
        if len(square) > MAX_SQUARE_TEXT_CHARS or len(piece) > 1:
            return self._error("Неправильне поле або фігура." if self.lang == "uk" else "Invalid square or piece.")
        square = square.strip().lower()
        if not re.fullmatch(r"[a-h][1-8]", square):
            return self._error("Неправильне поле." if self.lang == "uk" else "Invalid square.")
        normalized_piece = None if piece in {"", "-"} else piece
        try:
            state = self._position_state_from_live_board().with_piece(square, normalized_piece)
        except (PositionValidationError, ValueError):
            return self._error("Неправильна фігура." if self.lang == "uk" else "Invalid piece.")
        return self._commit_position_editor_state(
            state,
            f"Поле {square}: " + ("очищено." if normalized_piece is None else f"встановлено {PIECE_UK[normalized_piece]}."),
            f"Square {square}: " + ("cleared." if normalized_piece is None else f"set to {PIECE_EN[normalized_piece]}."),
        )

    def edit_position_metadata(
        self,
        turn: str,
        castling: str,
        en_passant: str,
        halfmove_text: str,
        fullmove_text: str,
    ) -> dict[str, Any]:
        values = (turn, castling, en_passant, halfmove_text, fullmove_text)
        if any(type(value) is not str for value in values):
            return self._error("Неправильні параметри позиції." if self.lang == "uk" else "Invalid position metadata.")
        if (
            len(turn) > 1
            or len(castling) > MAX_FEN_CHARS
            or len(en_passant) > MAX_SQUARE_TEXT_CHARS
            or len(halfmove_text) > MAX_FEN_CHARS
            or len(fullmove_text) > MAX_FEN_CHARS
        ):
            return self._error("Неправильні параметри позиції." if self.lang == "uk" else "Invalid position metadata.")
        if turn not in {"w", "b"}:
            return self._error("Неправильний колір." if self.lang == "uk" else "Invalid color.")
        if not halfmove_text.isascii() or not halfmove_text.isdecimal() or not fullmove_text.isascii() or not fullmove_text.isdecimal():
            return self._error("Лічильники ходів мають бути цілими невід’ємними числами." if self.lang == "uk" else "Move counters must be unsigned integers.")
        try:
            state = self._position_state_from_live_board()
            normalized_castling = state.with_castling(castling).castling
            state = PositionState(
                state.pieces,
                turn=turn,
                castling=normalized_castling,
                en_passant=en_passant.strip().lower() or "-",
                halfmove=int(halfmove_text),
                fullmove=int(fullmove_text),
            )
        except (PositionValidationError, ValueError):
            return self._error("Неправильні параметри позиції." if self.lang == "uk" else "Invalid position metadata.")
        return self._commit_position_editor_state(
            state,
            "Параметри позиції оновлено.",
            "Position metadata updated.",
        )

    def _localized_position_problem(self, problem: str) -> str:
        if self.lang != "uk":
            return problem
        if problem.startswith("white king count must be 1"):
            return "має бути рівно один білий король"
        if problem.startswith("black king count must be 1"):
            return "має бути рівно один чорний король"
        if problem.startswith("pawn on invalid first rank at "):
            return "пішак не може стояти на першій горизонталі: " + problem.rsplit(" ", 1)[-1]
        if problem.startswith("pawn on invalid eighth rank at "):
            return "пішак не може стояти на восьмій горизонталі: " + problem.rsplit(" ", 1)[-1]
        if "castling right inconsistent" in problem:
            return "права рокіровки не відповідають розташуванню короля і тури"
        return "структура позиції некоректна"

    def validate_position_editor(self) -> dict[str, Any]:
        try:
            state = self._position_state_from_live_board()
            structural = state.validate_playable()
            if structural:
                problems = [self._localized_position_problem(item) for item in structural]
                return self._error(
                    ("Позиція ще не готова до гри: " if self.lang == "uk" else "Position is not yet playable: ")
                    + "; ".join(problems)
                )
            Board(state.to_fen())
        except (PositionValidationError, ValueError):
            return self._error("Позиція не пройшла перевірку легальності." if self.lang == "uk" else "Position failed legality validation.")
        return self._ok("Позиція коректна і готова до гри." if self.lang == "uk" else "Position is valid and ready to play.")

    def set_position_text(self, text: str, turn: str | None = None) -> dict[str, Any]:
        try:
            side = self.board.turn if turn is None else turn
            fen = parse_position_text(text, side, language=self.lang)
        except ValueError as exc:
            # The position-text adapter owns localized, presentation-safe
            # diagnostics for expected parse failures.
            return self._error(str(exc))
        except Exception:
            return self._error(self._t("position_invalid"))

        try:
            candidate_board = Board(fen)
        except ValueError as exc:
            # Core chess validation is historically Ukrainian. Preserve those
            # useful details in Ukrainian mode, but never make NVDA read them
            # inside an English interface.
            return self._error(str(exc) if self.lang == "uk" else self._t("position_invalid"))
        except Exception:
            return self._error(self._t("position_invalid"))

        try:
            prepared = self._prepare_root_state(candidate_board)
        except Exception:
            return self._error(self._t("position_history_failed"))

        self._publish_root_state(candidate_board, prepared)
        return self._ok("Позицію завантажено з текстового редактора." if self.lang == "uk"
                        else "Position loaded from text editor.")

    def toggle_engine(self) -> dict[str, Any]:
        self.engine_enabled = not self.engine_enabled
        if self.engine_enabled:
            return self._ok("Аналіз Stockfish увімкнено." if self.lang == "uk"
                            else "Stockfish analysis enabled.")
        return self._ok("Аналіз Stockfish вимкнено." if self.lang == "uk" else "Stockfish analysis disabled.")

    def make_move(self, text: str) -> dict[str, Any]:
        if type(text) is not str:
            return self._error(self._t("move_text_type"))
        if len(text) > MAX_MOVE_ENTRY_CHARS:
            return self._error(self._t("move_text_too_long"))
        text = text.strip()
        if not text:
            return self._error("Введіть хід." if self.lang == "uk" else "Enter a move.")
        commands = {
            "u": self.undo, "y": self.redo,
            "l": lambda: self._ok(("Останній хід: " if self.lang == "uk" else "Last move: ") + self.get_state()["lastMove"]),
            "w": lambda: self.set_turn("w"), "b": lambda: self.set_turn("b"), "c": self.clear_board,
            "s": self.new_game, "e": self.toggle_engine,
        }
        if len(text) == 1 and text in commands:
            return commands[text]()
        if not self._at_history_end():
            return self._error(self._t("review_before_move"))
        if not self._position_complete(self.board):
            return self._error(self._t("setup_incomplete"))
        if not self._position_playable(self.board):
            return self._error(self._t("position_invalid"))
        side = self.board.turn
        try:
            candidate_board = copy.deepcopy(self.board)
        except Exception:
            return self._error(self._t("move_history_failed"))
        try:
            san = candidate_board.push_text(text)
        except ValueError:
            # Accept lowercase piece letters at the human-input boundary only.
            # Try exact SAN first: bxc3 must remain a pawn capture when valid.
            # PGN/Board parsing and canonical disambiguation stay unchanged.
            if not re.fullmatch(r"[kqrbn](?:[a-h][1-8]?|[1-8])?x?[a-h][1-8][+#]?", text):
                return self._error(self._t("move_invalid"))
            try:
                candidate_board = copy.deepcopy(self.board)
                san = candidate_board.push_text(text[0].upper() + text[1:])
            except ValueError:
                return self._error(self._t("move_invalid"))
            except Exception:
                return self._error(self._t("move_history_failed"))
        except Exception:
            return self._error(self._t("move_history_failed"))
        try:
            candidate_history = ReviewHistory.from_tree(self.review_history.export_tree())
            candidate_sans = list(self.sans)
            candidate_sides = list(self.move_sides)
            candidate_sans.append(san)
            candidate_sides.append(side)
            selection = candidate_history.append(
                candidate_board.fen(),
                san=san,
                side=side,
                last_move=san,
            )
            candidate_adapter, candidate_live_node = self._prepare_live_presentation(
                candidate_board,
                candidate_history,
            )
            if selection.node_id != candidate_live_node:
                raise RuntimeError("candidate move cursor mismatch")
        except Exception:
            return self._error(self._t("move_history_failed"))
        self._publish_live_transaction(
            candidate_board,
            candidate_history,
            candidate_adapter,
            candidate_live_node,
            sans=candidate_sans,
            move_sides=candidate_sides,
            redo_meta=[],
        )
        return self._ok(
            ("Зіграно: " if self.lang == "uk" else "Played: ")
            + format_san(san, "uk_literal" if self.lang == "uk" else "en_literal")
        )

    def activate_square(self, square: str) -> dict[str, Any]:
        if not self._at_history_end():
            return self._error(self._t("review_before_move"))
        try:
            target = parse_sq(square)
        except ValueError as exc:
            return self._error(str(exc) if self.lang == "uk" else self._t("square_invalid"))
        except Exception:
            return self._error(self._t("square_invalid"))
        if not self._position_complete(self.board):
            return self._error(self._t("setup_incomplete"))
        if not self._position_playable(self.board):
            return self._error(self._t("position_invalid"))
        p = self.board.board[target]
        if self.selected_source is None:
            if not p:
                return self._error(self.square_label(target, self.board))
            if color_of(p) != self.board.turn:
                msg = ("Зараз хід іншої сторони. " if self.lang == "uk" else "It is the other side's turn. ") + self.square_label(target, self.board)
                return self._error(msg)
            self.selected_source = target
            return self._ok(f"{self.square_label(target, self.board)}, {self._t('selected')}")
        source = self.selected_source
        if source == target:
            self.selected_source = None
            return self._ok("Вибір скасовано." if self.lang == "uk" else "Selection cancelled.")
        candidates = [m for m in self.board.legal_moves() if m.frm == source and m.to == target]
        if not candidates:
            if p and color_of(p) == self.board.turn:
                self.selected_source = target
                return self._ok(f"{self.square_label(target, self.board)}, {self._t('selected')}")
            return self._error(self._t("illegal"))
        move = next((m for m in candidates if m.promotion == "Q"), candidates[0])
        side = self.board.turn
        try:
            candidate_board = copy.deepcopy(self.board)
        except Exception:
            return self._error(self._t("move_history_failed"))
        try:
            san = candidate_board.push(move)
        except Exception:
            # A move selected from legal_moves() failing here is an internal
            # synchronization failure, not user-authored diagnostic text.
            return self._error(self._t("move_history_failed"))
        try:
            candidate_history = ReviewHistory.from_tree(self.review_history.export_tree())
            candidate_sans = list(self.sans)
            candidate_sides = list(self.move_sides)
            candidate_sans.append(san)
            candidate_sides.append(side)
            selection = candidate_history.append(
                candidate_board.fen(),
                san=san,
                side=side,
                last_move=san,
            )
            candidate_adapter, candidate_live_node = self._prepare_live_presentation(
                candidate_board,
                candidate_history,
            )
            if selection.node_id != candidate_live_node:
                raise RuntimeError("candidate move cursor mismatch")
        except Exception:
            return self._error(self._t("move_history_failed"))
        self._publish_live_transaction(
            candidate_board,
            candidate_history,
            candidate_adapter,
            candidate_live_node,
            sans=candidate_sans,
            move_sides=candidate_sides,
            redo_meta=[],
        )
        return self._ok(
            ("Зіграно: " if self.lang == "uk" else "Played: ")
            + format_san(san, "uk_literal" if self.lang == "uk" else "en_literal")
        )

    def cancel_selection(self) -> dict[str, Any]:
        self.selected_source = None
        return self._ok("Вибір скасовано." if self.lang == "uk" else "Selection cancelled.")

    def undo(self) -> dict[str, Any]:
        if not self._at_history_end():
            return self._error(self._t("review_before_move"))
        if not self.sans:
            return self._error(self._t("undo_none"))
        try:
            candidate_board, candidate_history = self._clone_live_transaction()
            records = {
                record.node_id: record
                for record in candidate_history.tree_nodes()
            }
            parent_id = records[self.live_history_node].parent_id
            if parent_id is None:
                return self._error(self._t("undo_none"))
            candidate_sans = list(self.sans)
            candidate_sides = list(self.move_sides)
            candidate_redo = list(self.redo_meta)
            expected_san = candidate_sans[-1]
            side = candidate_sides[-1]
            san = candidate_board.undo()
            if san is None:
                return self._error(self._t("undo_none"))
            if san != expected_san:
                raise RuntimeError("candidate undo SAN mismatch")
            candidate_sans.pop()
            candidate_sides.pop()
            candidate_redo.append((san, side))
            selection = candidate_history.select_node(parent_id)
            if selection.snapshot.fen != candidate_board.fen():
                raise RuntimeError("candidate undo FEN mismatch")
            candidate_adapter, candidate_live_node = self._prepare_live_presentation(
                candidate_board,
                candidate_history,
            )
            if selection.node_id != candidate_live_node:
                raise RuntimeError("candidate undo cursor mismatch")
        except Exception:
            return self._error(self._t("move_history_failed"))
        self._publish_live_transaction(
            candidate_board,
            candidate_history,
            candidate_adapter,
            candidate_live_node,
            sans=candidate_sans,
            move_sides=candidate_sides,
            redo_meta=candidate_redo,
        )
        return self._ok(
            ("Скасовано: " if self.lang == "uk" else "Undone: ")
            + format_san(san, "uk_literal" if self.lang == "uk" else "en_literal")
        )

    def redo(self) -> dict[str, Any]:
        if not self._at_history_end():
            return self._error(self._t("review_before_move"))
        if not self.redo_meta:
            return self._error(self._t("redo_none"))
        try:
            candidate_board, candidate_history = self._clone_live_transaction()
            records = {
                record.node_id: record
                for record in candidate_history.tree_nodes()
            }
            child_id = records[self.live_history_node].active_child
            if child_id is None:
                return self._error(self._t("redo_none"))
            candidate_sans = list(self.sans)
            candidate_sides = list(self.move_sides)
            candidate_redo = list(self.redo_meta)
            meta_san, side = candidate_redo[-1]
            san = candidate_board.redo()
            if san is None:
                return self._error(self._t("redo_none"))
            if san != meta_san:
                raise RuntimeError("candidate redo SAN mismatch")
            candidate_redo.pop()
            candidate_sans.append(meta_san)
            candidate_sides.append(side)
            selection = candidate_history.select_node(child_id)
            if selection.snapshot.fen != candidate_board.fen():
                raise RuntimeError("candidate redo FEN mismatch")
            if selection.snapshot.san not in (None, meta_san):
                raise RuntimeError("candidate redo history SAN mismatch")
            candidate_adapter, candidate_live_node = self._prepare_live_presentation(
                candidate_board,
                candidate_history,
            )
            if selection.node_id != candidate_live_node:
                raise RuntimeError("candidate redo cursor mismatch")
        except Exception:
            return self._error(self._t("move_history_failed"))
        self._publish_live_transaction(
            candidate_board,
            candidate_history,
            candidate_adapter,
            candidate_live_node,
            sans=candidate_sans,
            move_sides=candidate_sides,
            redo_meta=candidate_redo,
        )
        return self._ok(
            ("Повторено: " if self.lang == "uk" else "Redone: ")
            + format_san(meta_san, "uk_literal" if self.lang == "uk" else "en_literal")
        )

    def set_turn(self, color: str) -> dict[str, Any]:
        if not self._at_history_end():
            return self._error(self._t("review_before_move"))
        if type(color) is not str or color not in ("w", "b"):
            return self._error("Неправильний колір." if self.lang == "uk" else "Invalid color.")
        try:
            # Route manual side-to-move edits through the canonical editable
            # position transition.  A manually changed turn has no trustworthy
            # preceding double-pawn move, so stale en-passant state must not
            # survive the edit.
            state = self._position_state_from_live_board().with_turn(color)
        except (PositionValidationError, ValueError):
            return self._error(self._t("position_invalid"))
        return self._commit_position_editor_state(
            state,
            self._t("white_turn") if color == "w" else self._t("black_turn"),
            self._t("white_turn") if color == "w" else self._t("black_turn"),
        )

    def set_fen(self, fen: str) -> dict[str, Any]:
        if type(fen) is not str:
            return self._error(self._t("fen_text_type"))
        if len(fen) > MAX_FEN_CHARS:
            return self._error(self._t("fen_text_too_long"))
        try:
            candidate_board = Board(fen)
        except ValueError as exc:
            return self._error(str(exc) if self.lang == "uk" else self._t("fen_invalid"))
        except Exception:
            return self._error(self._t("fen_invalid"))

        try:
            prepared = self._prepare_root_state(candidate_board)
        except Exception:
            return self._error(self._t("fen_history_failed"))

        self._publish_root_state(candidate_board, prepared)
        return self._ok("FEN завантажено." if self.lang == "uk" else "FEN loaded.")

    def set_language(self, lang: str) -> dict[str, Any]:
        if type(lang) is not str or lang not in ("uk", "en"):
            return self._error("Unsupported language")
        try:
            candidate_adapter = ReviewPresentationAdapter(self.review_history, language=lang)
        except Exception:
            return self._error(self._t("language_change_failed"))
        self.lang = lang
        self.review_adapter = candidate_adapter
        return self._ok("Мову змінено." if lang == "uk" else "Language changed.")

    def diagnostic(self) -> dict[str, Any]:
        test = Board()
        test.push_text("e4")
        live_board = self.board
        label_empty = self.square_label("e4", live_board) if live_board.board[parse_sq("e4")] else "e 4"
        html = _asset_root() / "web" / "index.html"
        semantic = False
        history_ui = False
        if html.exists():
            text = html.read_text(encoding="utf-8")
            semantic = all(marker in text for marker in (
                '<main id="main-content">', '<h2 id="h-game-info">', 'id="move-input" type="text"',
                'id="position-input"', 'id="empty-board" type="button"',
                'role="status" aria-live="polite"', 'role="application" aria-label="Шахова дошка"',
            ))
            history_ui = all(marker in text for marker in (
                'id="history-input" type="text"', 'id="history-prev" type="button"',
                'id="history-next" type="button"', 'Ctrl+G', 'Shift+A', 'Shift+D',
            ))
        return {
            "ok": True, "version": VERSION, "boardCells": len(self._board_cells()),
            "emptySquareCoordinateOnly": "," not in label_empty if not live_board.board[parse_sq("e4")] else True,
            "semanticDocumentPresent": semantic, "historyUiPresent": history_ui,
        }


def _make_menu(webview: Any, api: AccessibleChessAPI, window_holder: dict[str, Any]):
    Menu = webview.menu.Menu
    MenuAction = webview.menu.MenuAction
    MenuSeparator = webview.menu.MenuSeparator

    def js(code: str) -> None:
        w = window_holder.get("window")
        if w:
            try:
                w.evaluate_js(code)
            except Exception:
                pass

    def refresh_action(fn):
        def wrapped():
            fn()
            js("refreshState()")
        return wrapped

    return [
        Menu("Файл", [
            MenuAction("Нова стандартна позиція", refresh_action(api.new_game)),
            MenuAction("Порожня дошка", refresh_action(api.clear_board)),
            MenuSeparator(),
            MenuAction("Вихід", lambda: window_holder.get("window") and window_holder["window"].destroy()),
        ]),
        Menu("Гра", [
            MenuAction("Скасувати хід", refresh_action(api.undo)),
            MenuAction("Повторити хід", refresh_action(api.redo)),
            MenuSeparator(),
            MenuAction("Попередня позиція в історії", refresh_action(api.review_previous)),
            MenuAction("Наступна позиція в історії", refresh_action(api.review_next)),
            MenuAction("Перейти до ходу", lambda: js("focusHistoryJump()")),
        ]),
        Menu("Дошка", [
            MenuAction("Перейти на дошку", lambda: js("enterBoard()")),
            MenuAction("Поле введення ходу", lambda: js("document.getElementById('move-input').focus()")),
            MenuAction("Текстовий редактор позиції", lambda: js("document.getElementById('position-input').focus()")),
        ]),
        Menu("Аналіз", [MenuAction("Увімкнути / вимкнути Stockfish", refresh_action(api.toggle_engine))]),
        Menu("Налаштування", [MenuAction("Доступність — семантичний WebView2 документ", lambda: None)]),
        Menu("Довідка", [MenuAction("Клавіші", lambda: js("document.getElementById('help').focus()"))]),
    ]


def main() -> None:
    import webview

    api = AccessibleChessAPI()
    window_holder: dict[str, Any] = {}
    html = _asset_root() / "web" / "index.html"
    if not html.exists():
        raise RuntimeError(f"Accessible HTML UI not found: {html}")
    menu = _make_menu(webview, api, window_holder)
    window = webview.create_window(
        "Accessible Chess — 0.4 NVDA architecture",
        url=str(html), js_api=api, width=1150, height=820, min_size=(800, 600),
        text_select=True, menu=menu,
    )
    window_holder["window"] = window
    webview.start(gui="edgechromium", private_mode=True)


if __name__ == "__main__":
    main()
