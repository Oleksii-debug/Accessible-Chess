from __future__ import annotations

"""Stage 1 saturation facade over the frozen WebView/keymap implementation.

The frozen 656e8ec implementation is retained byte-for-byte in
``webapp_keymap_core``.  This facade closes Stage 1 board-command integration
without importing Stage 2 services or changing the QA-owned Windows harness.
"""

from typing import Any

from . import webapp as _webapp
from . import webapp_keymap_core as _core
from .webapp_keymap_core import *  # noqa: F401,F403 - compatibility surface
from .webapp_keymap_core import AccessibleChessAPI, _asset_root, _shared_spoken_san
from .board_service import BoardCommandService, BoardSnapshot, MoveView
from .chesscore import Board, parse_sq, sq_name
from .webapp import MAX_MOVE_ENTRY_CHARS


_BaseKeymapAwareAccessibleChessAPI = _core.KeymapAwareAccessibleChessAPI

_PIECE_KIND_BY_ACTION = {
    "king": "K",
    "queen": "Q",
    "rook": "R",
    "bishop": "B",
    "knight": "N",
    "pawn": "P",
}


def _canonical_controllers(board: Board, target: int) -> tuple[int, ...]:
    """Return controller origins using the canonical chess move generator.

    Attack/defence is presentation information, but piece geometry must stay in
    the canonical chess core.  A temporary opposite-colour target piece makes
    ``Board.pseudo_moves`` expose captures into an empty or friendly-occupied
    square without accidentally treating a pawn's straight advance as control.
    The probe is detached and never mutates the displayed board.
    """

    origins: set[int] = set()
    for color in ("w", "b"):
        probe = Board(board.fen())
        probe.board[target] = "n" if color == "w" else "N"
        for move in probe.pseudo_moves(color):
            if move.to == target and not move.castle:
                origins.add(move.frm)
    return tuple(sorted(origins))


class KeymapAwareAccessibleChessAPI(_BaseKeymapAwareAccessibleChessAPI):
    """Complete the central board action surface declared by ActionRegistry."""

    def keymap_resolve_binding(self, context: str, binding: str) -> dict[str, Any] | None:
        """Resolve the WebView board focus hierarchy without duplicating rules in JS.

        Board focus intentionally exposes board commands, Analysis commands, and
        Global commands in that order. ``ActionRegistry`` keeps its presentation-
        neutral ``context -> global`` fallback, so the WebView bridge composes the
        additional Analysis layer here and remains the single authoritative
        resolver for persisted remaps.
        """

        if context != "board":
            return super().keymap_resolve_binding(context, binding)
        try:
            board_or_global = self.keymap_service.resolve_binding("board", binding)
            if board_or_global is not None and board_or_global.get("context") == "board":
                return board_or_global

            analysis_or_global = self.keymap_service.resolve_binding("analysis", binding)
            if analysis_or_global is not None and analysis_or_global.get("context") == "analysis":
                return analysis_or_global
            return board_or_global
        except Exception:
            return None

    def make_move(self, text: str) -> dict[str, Any]:
        # Null moves remain import/notation pseudo-moves, never manual gameplay.
        # Everything else must pass through the central keymap composition: it
        # owns remapped aliases, temporary-analysis fencing, canonical position
        # readiness and the shared transactional move publisher.
        if type(text) is not str:
            return super().make_move(text)
        if len(text) > MAX_MOVE_ENTRY_CHARS:
            return super().make_move(text)
        if self.board.norm_san(text) == "--":
            return self._error(
                "Нульовий хід не можна грати вручну."
                if self.lang == "uk"
                else "A null move cannot be played manually."
            )
        return super().make_move(text)

    def _board_query_board(self) -> Board:
        exploration = self.analysis_ui.exploration
        if exploration is not None and self._analysis_origin_matches():
            return Board(exploration.fen)
        return self._display_board()

    def _board_query_service(self, *, control_square: str | None = None) -> BoardCommandService:
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
        if control_square is not None:
            target = parse_sq(control_square)
            origins = _canonical_controllers(board, target)
            if origins:
                attacks[target] = origins
        return BoardCommandService(
            BoardSnapshot(tuple(board.board), board.turn, tuple(legal), attacks)
        )

    def _board_square(self, square: str | None) -> str:
        if type(square) is not str:
            raise ValueError("board square is required")
        return sq_name(parse_sq(square))

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

        # This projection is owned by Stage1ReleaseAccessibleChessAPI and is a
        # closed-world built-in dict. Prove that passive root before any mapping
        # hook, then bound/validate keys before keyed lookup can encounter an
        # active str subclass stored by a substituted provider.
        if type(game) is not dict or len(game) > 20:
            return None, None
        for key in game:
            if type(key) is not str:
                return None, None

        configured = game.get("configured")
        if type(configured) is not bool or not configured:
            return None, None

        initial = game.get("initialMinutes", 0)
        increment = game.get("incrementSeconds", 0)
        if (
            type(initial) is not int
            or type(increment) is not int
            or initial < 0
            or increment < 0
        ):
            return None, None
        if initial == 0 and increment == 0:
            untimed = "Untimed" if self.lang == "en" else "Без годинника"
            return untimed, untimed

        human = game.get("humanSide")
        white_clock = game.get("whiteClock")
        black_clock = game.get("blackClock")
        if (
            type(human) is not str
            or human not in {"w", "b"}
            or type(white_clock) is not str
            or type(black_clock) is not str
        ):
            return None, None
        if human == "w":
            return white_clock, black_clock
        return black_clock, white_clock

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
        if type(action_id) is not str:
            return self._error("Команда недоступна." if self.lang == "uk" else "Command unavailable.")
        action = action_id.strip()

        if not action.startswith("board."):
            return super().dispatch_action(action)

        board = self._board_query_board()
        service = self._board_query_service()

        if action == "board.read_fen":
            fen = board.fen()
            result = self._ok(("FEN позиції: " if self.lang == "uk" else "Position FEN: ") + fen)
            result["fen"] = fen
            return result
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
        if action in {"board.evaluation", "board.best_move", "board.play_best"}:
            # play_best intentionally remains explicit-unavailable in Stage 1;
            # do not turn an informational key into a hidden mutation path.
            return super().dispatch_action(action)

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
            if action in {"board.attackers", "board.defenders"}:
                service = self._board_query_service(control_square=current)
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
