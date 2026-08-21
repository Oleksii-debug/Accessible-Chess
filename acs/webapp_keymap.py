from __future__ import annotations

"""Stage 1 saturation facade over the frozen WebView/keymap implementation.

The frozen 656e8ec implementation is retained byte-for-byte in
``webapp_keymap_core``.  This facade closes Stage 1 board-command integration
without importing Stage 2 services or changing the QA-owned Windows harness.
"""

from typing import Any

from . import webapp_keymap_core as _core
from .webapp_keymap_core import *  # noqa: F401,F403 - compatibility surface
from .webapp_keymap_core import AccessibleChessAPI, _asset_root, _shared_spoken_san
from .board_service import BoardCommandService, BoardSnapshot, MoveView
from .chesscore import Board, color_of, parse_sq, sq_name


_BaseKeymapAwareAccessibleChessAPI = _core.KeymapAwareAccessibleChessAPI

_PIECE_KIND_BY_ACTION = {
    "king": "K",
    "queen": "Q",
    "rook": "R",
    "bishop": "B",
    "knight": "N",
    "pawn": "P",
}


def _piece_controls_square(board: Board, origin: int, target: int) -> bool:
    """Return geometric chess control without mutating canonical state."""

    if origin == target:
        return False
    piece = board.board[origin]
    if not piece:
        return False
    of, orank = origin % 8, origin // 8
    tf, trank = target % 8, target // 8
    df, dr = tf - of, trank - orank
    kind = piece.upper()

    if kind == "P":
        step = 1 if piece.isupper() else -1
        return dr == step and abs(df) == 1
    if kind == "N":
        return (abs(df), abs(dr)) in {(1, 2), (2, 1)}
    if kind == "K":
        return max(abs(df), abs(dr)) == 1

    if kind == "B":
        if abs(df) != abs(dr):
            return False
    elif kind == "R":
        if not ((df == 0) ^ (dr == 0)):
            return False
    elif kind == "Q":
        if not (abs(df) == abs(dr) or ((df == 0) ^ (dr == 0))):
            return False
    else:
        return False

    step_f = 0 if df == 0 else (1 if df > 0 else -1)
    step_r = 0 if dr == 0 else (1 if dr > 0 else -1)
    f, r = of + step_f, orank + step_r
    while (f, r) != (tf, trank):
        if board.board[r * 8 + f] is not None:
            return False
        f += step_f
        r += step_r
    return True


class KeymapAwareAccessibleChessAPI(_BaseKeymapAwareAccessibleChessAPI):
    """Complete the central board action surface declared by ActionRegistry."""

    def _board_query_board(self) -> Board:
        exploration = self.analysis_ui.exploration
        if exploration is not None and self._analysis_origin_matches():
            return Board(exploration.fen)
        return self._display_board()

    def _board_query_service(self) -> BoardCommandService:
        board = self._board_query_board()
        legal: list[MoveView] = []
        if self._position_complete(board):
            for move in board.legal_moves():
                try:
                    san = board.san(move)
                except Exception:
                    san = None
                legal.append(
                    MoveView(
                        move.frm,
                        move.to,
                        san,
                        bool(board.board[move.to]) or bool(move.en_passant),
                    )
                )
        attacks: dict[int, tuple[int, ...]] = {}
        for target in range(64):
            origins = tuple(
                origin
                for origin, piece in enumerate(board.board)
                if piece and _piece_controls_square(board, origin, target)
            )
            if origins:
                attacks[target] = origins
        return BoardCommandService(
            BoardSnapshot(tuple(board.board), board.turn, tuple(legal), attacks)
        )

    def _board_square(self, square: str | None) -> str:
        if not isinstance(square, str):
            raise ValueError("board square is required")
        index = parse_sq(square)
        return sq_name(index)

    def _board_list_message(self, heading_uk: str, heading_en: str, values: list[str]) -> str:
        heading = heading_en if self.lang == "en" else heading_uk
        if not values:
            return f"{heading}: " + ("none." if self.lang == "en" else "немає.")
        return f"{heading}: " + ", ".join(values) + "."

    def _last_captured_piece(self) -> str | None:
        view = self._display_review()
        records = {record.node_id: record for record in self.review_history.tree_nodes()}
        record = records.get(view.node_id)
        if record is None or record.parent_id is None:
            return None
        san = record.snapshot.san or record.snapshot.last_move
        if not isinstance(san, str) or "x" not in san:
            return None
        parent = records.get(record.parent_id)
        if parent is None:
            return None
        try:
            board = Board(parent.snapshot.fen)
            move = board.parse_move(san)
            if move.en_passant:
                capture_square = move.to - 8 if board.board[move.frm] == "P" else move.to + 8
                return board.board[capture_square]
            return board.board[move.to]
        except Exception:
            return None

    def _clock_pair(self) -> tuple[str | None, str | None]:
        projection = getattr(self, "_engine_game_projection", None)
        if not callable(projection):
            return None, None
        try:
            game = projection()
        except Exception:
            return None, None
        if not game.get("configured"):
            return None, None
        if int(game.get("initialMinutes", 0)) == 0 and int(game.get("incrementSeconds", 0)) == 0:
            untimed = "Untimed" if self.lang == "en" else "Без годинника"
            return untimed, untimed
        human = game.get("humanSide")
        if human == "w":
            return str(game.get("whiteClock") or ""), str(game.get("blackClock") or "")
        if human == "b":
            return str(game.get("blackClock") or ""), str(game.get("whiteClock") or "")
        return None, None

    def _material_message(self, service: BoardCommandService) -> str:
        material = service.material()
        labels_uk = {"Q": "ферзь", "R": "тура", "B": "слон", "N": "кінь", "P": "пішак"}
        labels_en = {"Q": "queen", "R": "rook", "B": "bishop", "N": "knight", "P": "pawn"}
        labels = labels_en if self.lang == "en" else labels_uk

        def side_text(values: Any) -> str:
            parts = [f"{labels[k]} {values[k]}" for k in ("Q", "R", "B", "N", "P") if values[k]]
            return ", ".join(parts) if parts else ("none" if self.lang == "en" else "немає")

        if self.lang == "en":
            return (
                f"Material. White: {side_text(material.white)}; Black: {side_text(material.black)}. "
                f"Points {material.white_points} to {material.black_points}; balance {material.balance:+d}."
            )
        return (
            f"Матеріал. Білі: {side_text(material.white)}; чорні: {side_text(material.black)}. "
            f"Очки {material.white_points} до {material.black_points}; баланс {material.balance:+d}."
        )

    def _focus_result(self, message: str, square: str) -> dict[str, Any]:
        result = self._ok(message)
        result["focusSquare"] = square
        return result

    def dispatch_action(self, action_id: str, square: str | None = None) -> dict[str, Any]:
        if not isinstance(action_id, str):
            return self._error("Команда недоступна." if self.lang == "uk" else "Command unavailable.")
        action = action_id.strip()

        # Existing analysis/global actions retain the frozen implementation.
        if not action.startswith("board."):
            return super().dispatch_action(action)

        board = self._board_query_board()
        service = self._board_query_service()

        if action == "board.material":
            return self._ok(self._material_message(service))
        if action == "board.last_move":
            last = self._display_review().last_move
            if last:
                rendered = _shared_spoken_san(last, self.lang)
                return self._ok(("Останній хід: " if self.lang == "uk" else "Last move: ") + rendered)
            return self._error("Останнього ходу немає." if self.lang == "uk" else "There is no last move.")
        if action == "board.last_captured":
            piece = self._last_captured_piece()
            if piece:
                return self._ok(("Остання взята фігура: " if self.lang == "uk" else "Last captured piece: ") + self._piece_name(piece) + ".")
            return self._error("Останньої взятої фігури немає." if self.lang == "uk" else "There is no last captured piece.")
        if action in {"board.my_clock", "board.opponent_clock"}:
            mine, opponent = self._clock_pair()
            value = mine if action == "board.my_clock" else opponent
            if value is None:
                return self._error("Годинник недоступний." if self.lang == "uk" else "Clock unavailable.")
            label = (
                "Мій час" if action == "board.my_clock" and self.lang == "uk"
                else "Час суперника" if self.lang == "uk"
                else "My clock" if action == "board.my_clock"
                else "Opponent clock"
            )
            return self._ok(f"{label}: {value}.")
        if action == "board.evaluation" or action == "board.best_move":
            return super().dispatch_action(action)
        if action == "board.play_best":
            try:
                line = self.analysis_ui.selected_line(self._display_review().fen)
                if not line.pv:
                    raise RuntimeError("empty analysis line")
                return self.make_move(str(line.pv[0]))
            except Exception:
                return self._error(
                    "Найкращий хід недоступний для гри."
                    if self.lang == "uk"
                    else "Best move is unavailable for play."
                )

        try:
            current = self._board_square(square)
        except Exception:
            return self._error(
                "Спочатку перейдіть на поле дошки."
                if self.lang == "uk"
                else "Move focus to a board square first."
            )

        if action == "board.current":
            return self._focus_result(self.square_label(current, board), current)
        if action == "board.legal_moves":
            values = [
                _shared_spoken_san(move.san or f"{sq_name(move.frm)}{sq_name(move.to)}", self.lang)
                for move in service.legal_moves(current)
            ]
            return self._focus_result(self._board_list_message("Легальні ходи", "Legal moves", values), current)
        if action == "board.captures":
            values = [
                _shared_spoken_san(move.san or f"{sq_name(move.frm)}{sq_name(move.to)}", self.lang)
                for move in service.captures(current)
            ]
            return self._focus_result(self._board_list_message("Взяття", "Captures", values), current)
        if action in {"board.surroundings", "board.attackers", "board.defenders"}:
            getter = {
                "board.surroundings": service.surroundings,
                "board.attackers": service.attackers,
                "board.defenders": service.defenders,
            }[action]
            values = [self.square_label(item.square, board) for item in getter(current)]
            headings = {
                "board.surroundings": ("Оточення", "Surroundings"),
                "board.attackers": ("Атакуючі", "Attackers"),
                "board.defenders": ("Захисники", "Defenders"),
            }
            uk, en = headings[action]
            return self._focus_result(self._board_list_message(uk, en, values), current)

        import re
        match = re.fullmatch(r"board\.(next|previous)_(king|queen|rook|bishop|knight|pawn)", action)
        if match:
            direction = 1 if match.group(1) == "next" else -1
            piece_kind = _PIECE_KIND_BY_ACTION[match.group(2)]
            target = service.cycle_piece(piece_kind, current, direction=direction)
            if target is None:
                return self._focus_result(
                    "Такої фігури немає." if self.lang == "uk" else "No such piece is present.",
                    current,
                )
            return self._focus_result(self.square_label(target.square, board), target.square)

        return super().dispatch_action(action)


def main() -> None:
    import webview

    api = KeymapAwareAccessibleChessAPI()
    html = _asset_root() / "web" / "index.html"
    if not html.exists():
        raise RuntimeError(f"Accessible HTML UI not found: {html}")
    window = webview.create_window(
        "Accessible Chess",
        url=str(html), js_api=api, width=1150, height=820, min_size=(800, 600),
        text_select=True,
    )

    def install_menu_on_native_host(*_args: Any) -> None:
        if not install_windows_native_menu(window, api):
            raise RuntimeError("Accessible native Windows menu could not be attached to the WebView2 host.")

    window.events.before_show += install_menu_on_native_host
    webview.start(gui="edgechromium", private_mode=True)
