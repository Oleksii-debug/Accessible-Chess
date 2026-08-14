from __future__ import annotations

"""Accessible WebView2 presentation layer for Accessible Chess.

The 0.3.x Tkinter surface failed the first real NVDA acceptance test. This
module keeps the chess core in Python but renders the user-facing document as
semantic HTML inside Edge/WebView2 on Windows. The HTML document is intended
to be consumed by NVDA browse/focus mode rather than by a self-voicing GUI.
"""

from pathlib import Path
import re
import sys
from typing import Any

from .chesscore import Board, parse_sq, sq_name, color_of
from .position_text import parse_position_text

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


def _spoken_san(san: str, lang: str = "uk") -> str:
    s = san.replace("O-O-O", "довга рокіровка" if lang == "uk" else "long castle")
    s = s.replace("O-O", "коротка рокіровка" if lang == "uk" else "short castle")
    s = re.sub(r"([a-h])([1-8])", lambda m: f"{m.group(1)} {m.group(2)}", s)
    if lang == "uk":
        s = s.replace("x", " б’є ").replace("+", ", шах").replace("#", ", мат")
    else:
        s = s.replace("x", " captures ").replace("+", ", check").replace("#", ", checkmate")
    return re.sub(r"\s+", " ", s).strip()


class AccessibleChessAPI:
    def __init__(self, lang: str = "uk") -> None:
        self.lang = lang if lang in ("uk", "en") else "uk"
        self.board = Board()
        self.start_fen = self.board.fen()
        self.sans: list[str] = []
        self.move_sides: list[str] = []
        self.redo_meta: list[tuple[str, str]] = []
        self.history_fens: list[str] = [self.start_fen]
        self.review_cursor = 0
        self.selected_source: int | None = None
        self.announcement = self._t("ready")
        self.mode = "analysis"
        self.engine_enabled = False

    def _t(self, key: str) -> str:
        uk = {
            "ready": "Готово. Документ доступності завантажено.",
            "white_turn": "Хід білих", "black_turn": "Хід чорних",
            "no_moves": "Ходів ще немає", "no_last": "Останнього ходу немає",
            "selected": "вибрано", "illegal": "Нелегальний хід",
            "undo_none": "Немає ходу для скасування", "redo_none": "Немає ходу для повторення",
            "setup_incomplete": "Редактор позиції. Додайте рівно по одному білому і чорному королю.",
            "review_start": "Початкова позиція.",
            "review_end": "Кінець історії.",
            "review_before_move": "Спочатку поверніться в кінець історії, щоб зробити новий хід.",
            "review_invalid": "Такої позиції в історії немає.",
        }
        en = {
            "ready": "Ready. Accessible document loaded.",
            "white_turn": "White to move", "black_turn": "Black to move",
            "no_moves": "No moves yet", "no_last": "No last move",
            "selected": "selected", "illegal": "Illegal move",
            "undo_none": "No move to undo", "redo_none": "No move to redo",
            "setup_incomplete": "Position editor. Add exactly one white king and one black king.",
            "review_start": "Initial position.",
            "review_end": "End of history.",
            "review_before_move": "Return to the end of history before playing a new move.",
            "review_invalid": "That historical position does not exist.",
        }
        return (uk if self.lang == "uk" else en).get(key, key)

    def _piece_name(self, p: str) -> str:
        return (PIECE_UK if self.lang == "uk" else PIECE_EN)[p]

    def _position_complete(self) -> bool:
        return self.board.board.count("K") == 1 and self.board.board.count("k") == 1

    def square_label(self, square: int | str) -> str:
        s = parse_sq(square) if isinstance(square, str) else int(square)
        coord = _spaced_square(sq_name(s))
        p = self.board.board[s]
        return coord if not p else f"{coord}, {self._piece_name(p)}"

    def _pieces_text(self, color: str) -> str:
        names = TYPE_UK if self.lang == "uk" else TYPE_EN
        lines: list[str] = []
        for typ in "KQRBNP":
            squares = [_spaced_square(sq_name(i)) for i, p in enumerate(self.board.board)
                       if p and p.upper() == typ and color_of(p) == color]
            if squares:
                lines.append(f"{names[typ]}: {', '.join(squares)}")
        return "\n".join(lines) if lines else ("фігур немає" if self.lang == "uk" else "no pieces")

    def _visible_ply_count(self) -> int:
        return min(self.review_cursor, len(self.sans))

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
                white = _spoken_san(sans[i], self.lang)
                if i + 1 < len(sans) and sides[i + 1] == "b":
                    black = _spoken_san(sans[i + 1], self.lang)
                    out.append(f"{move_no}. {white}, {black}.")
                    i += 2
                else:
                    out.append(f"{move_no}. {white}.")
                    i += 1
                move_no += 1
            else:
                out.append(f"{move_no}... {_spoken_san(sans[i], self.lang)}.")
                move_no += 1
                i += 1
        return "\n".join(out)

    def _game_status(self) -> str:
        turn_text = self._t("white_turn") if self.board.turn == "w" else self._t("black_turn")
        if not self._position_complete():
            return f"{self._t('setup_incomplete')} {turn_text}"
        legal = self.board.legal_moves()
        if legal:
            if self.board.in_check(self.board.turn):
                return turn_text + (". Шах." if self.lang == "uk" else ". Check.")
            return turn_text
        if self.board.in_check(self.board.turn):
            return ("Мат. " if self.lang == "uk" else "Checkmate. ") + turn_text
        return "Пат." if self.lang == "uk" else "Stalemate."

    def _board_cells(self) -> list[dict[str, Any]]:
        cells = []
        for rank in range(7, -1, -1):
            for file in range(8):
                sq = rank * 8 + file
                cells.append({
                    "square": sq_name(sq),
                    "label": self.square_label(sq),
                    "occupied": bool(self.board.board[sq]),
                    "selected": sq == self.selected_source,
                })
        return cells

    def _reset_history(self) -> None:
        self.sans.clear()
        self.move_sides.clear()
        self.redo_meta.clear()
        self.selected_source = None
        self.board.undo_stack = []
        self.board.redo_stack = []
        self.board.last_move = None
        self.history_fens = [self.board.fen()]
        self.review_cursor = 0

    def _at_history_end(self) -> bool:
        return self.review_cursor == len(self.sans)

    def _record_position_after_move(self) -> None:
        self.history_fens = self.history_fens[:len(self.sans)]
        self.history_fens.append(self.board.fen())
        self.review_cursor = len(self.sans)

    def _review_label(self, cursor: int | None = None) -> str:
        ply = self.review_cursor if cursor is None else cursor
        if ply <= 0:
            return "Початкова позиція" if self.lang == "uk" else "Initial position"
        full = (ply + 1) // 2
        if ply % 2:
            return (f"Позиція після {full}-го ходу білих" if self.lang == "uk"
                    else f"Position after White's move {full}")
        return (f"Позиція після {full}..." if self.lang == "uk"
                else f"Position after {full}...")

    def _load_review_cursor(self, cursor: int) -> dict[str, Any]:
        if cursor < 0 or cursor >= len(self.history_fens):
            return self._error(self._t("review_invalid"))
        self.review_cursor = cursor
        self.board = Board(self.history_fens[cursor])
        self.selected_source = None
        if cursor == 0:
            return self._ok(self._t("review_start"))
        if cursor == len(self.sans):
            return self._ok(self._t("review_end") + " " + self._review_label(cursor))
        return self._ok(self._review_label(cursor))

    def review_previous(self) -> dict[str, Any]:
        if self.review_cursor <= 0:
            return self._error(self._t("review_start"))
        return self._load_review_cursor(self.review_cursor - 1)

    def review_next(self) -> dict[str, Any]:
        if self.review_cursor >= len(self.sans):
            return self._error(self._t("review_end"))
        return self._load_review_cursor(self.review_cursor + 1)

    def go_to_move(self, target: str) -> dict[str, Any]:
        raw = (target or "").strip().lower()
        if raw in ("0", "start"):
            return self._load_review_cursor(0)
        if raw == "end":
            return self._load_review_cursor(len(self.sans))
        m = re.fullmatch(r"(\d+)\s*(w|b|\.\.\.)?", raw)
        if not m:
            return self._error(self._t("review_invalid"))
        move_no = int(m.group(1))
        if move_no <= 0:
            return self._error(self._t("review_invalid"))
        suffix = m.group(2)
        if suffix == "w":
            cursor = 2 * move_no - 1
        else:
            cursor = 2 * move_no
        if cursor > len(self.sans):
            return self._error(self._t("review_invalid"))
        return self._load_review_cursor(cursor)

    def get_state(self) -> dict[str, Any]:
        visible = self._visible_ply_count()
        last = _spoken_san(self.sans[visible - 1], self.lang) if visible else self._t("no_last")
        status = self._game_status()
        engine_status = (
            "Stockfish увімкнено. Перенесення MultiPV 5 ще триває." if self.lang == "uk" else
            "Stockfish enabled. MultiPV 5 migration is still in progress."
        ) if self.engine_enabled else (
            "Stockfish вимкнено." if self.lang == "uk" else "Stockfish disabled."
        )
        review_status = self._review_label()
        if self.review_cursor == len(self.sans):
            review_status += ("; кінець історії" if self.lang == "uk" else "; end of history")
        else:
            review_status += (
                f"; показано {self.review_cursor} з {len(self.sans)} півходів" if self.lang == "uk"
                else f"; showing {self.review_cursor} of {len(self.sans)} plies"
            )
        return {
            "version": VERSION, "lang": self.lang, "mode": self.mode,
            "gameInfo": f"Version: {VERSION}\n{status}",
            "moves": self._moves_text(), "whitePieces": self._pieces_text("w"), "blackPieces": self._pieces_text("b"),
            "gameStatus": status, "lastMove": last, "announcement": self.announcement,
            "fen": self.board.fen(), "board": self._board_cells(),
            "selectedSquare": sq_name(self.selected_source) if self.selected_source is not None else None,
            "engineEnabled": self.engine_enabled, "engineStatus": engine_status,
            "positionComplete": self._position_complete(),
            "reviewCursor": self.review_cursor, "historyLength": len(self.sans),
            "reviewStatus": review_status, "atHistoryEnd": self._at_history_end(),
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
        self.board = Board()
        self.start_fen = self.board.fen()
        self._reset_history()
        return self._ok("Стандартну позицію встановлено." if self.lang == "uk" else "Standard position loaded.")

    def clear_board(self) -> dict[str, Any]:
        self.board.board = [None] * 64
        self.board.turn = "w"
        self.board.castling = ""
        self.board.ep = None
        self.board.halfmove = 0
        self.board.fullmove = 1
        self.start_fen = self.board.fen()
        self._reset_history()
        return self._ok("Дошку очищено. Введіть позицію в редакторі." if self.lang == "uk"
                        else "Board cleared. Enter a position in the editor.")

    def set_position_text(self, text: str, turn: str | None = None) -> dict[str, Any]:
        try:
            side = turn if turn in ("w", "b") else self.board.turn
            fen = parse_position_text(text or "", side)
            self.board = Board(fen)
            self.start_fen = self.board.fen()
            self._reset_history()
            return self._ok("Позицію завантажено з текстового редактора." if self.lang == "uk"
                            else "Position loaded from text editor.")
        except Exception as exc:
            return self._error(str(exc))

    def toggle_engine(self) -> dict[str, Any]:
        self.engine_enabled = not self.engine_enabled
        if self.engine_enabled:
            return self._ok("Аналіз Stockfish увімкнено. MultiPV ще переноситься." if self.lang == "uk"
                            else "Stockfish analysis enabled. MultiPV migration is still in progress.")
        return self._ok("Аналіз Stockfish вимкнено." if self.lang == "uk" else "Stockfish analysis disabled.")

    def make_move(self, text: str) -> dict[str, Any]:
        text = (text or "").strip()
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
        if not self._position_complete():
            return self._error(self._t("setup_incomplete"))
        try:
            side = self.board.turn
            san = self.board.push_text(text)
            self.sans.append(san)
            self.move_sides.append(side)
            self.redo_meta.clear()
            self.selected_source = None
            self._record_position_after_move()
            return self._ok(("Зіграно: " if self.lang == "uk" else "Played: ") + _spoken_san(san, self.lang))
        except Exception as exc:
            return self._error(str(exc))

    def activate_square(self, square: str) -> dict[str, Any]:
        if not self._at_history_end():
            return self._error(self._t("review_before_move"))
        try:
            target = parse_sq(square)
        except Exception as exc:
            return self._error(str(exc))
        if not self._position_complete():
            return self._error(self._t("setup_incomplete"))
        p = self.board.board[target]
        if self.selected_source is None:
            if not p:
                return self._error(self.square_label(target))
            if color_of(p) != self.board.turn:
                msg = ("Зараз хід іншої сторони. " if self.lang == "uk" else "It is the other side's turn. ") + self.square_label(target)
                return self._error(msg)
            self.selected_source = target
            return self._ok(f"{self.square_label(target)}, {self._t('selected')}")
        source = self.selected_source
        if source == target:
            self.selected_source = None
            return self._ok("Вибір скасовано." if self.lang == "uk" else "Selection cancelled.")
        candidates = [m for m in self.board.legal_moves() if m.frm == source and m.to == target]
        if not candidates:
            if p and color_of(p) == self.board.turn:
                self.selected_source = target
                return self._ok(f"{self.square_label(target)}, {self._t('selected')}")
            return self._error(self._t("illegal"))
        move = next((m for m in candidates if m.promotion == "Q"), candidates[0])
        try:
            side = self.board.turn
            san = self.board.push(move)
            self.sans.append(san)
            self.move_sides.append(side)
            self.redo_meta.clear()
            self.selected_source = None
            self._record_position_after_move()
            return self._ok(("Зіграно: " if self.lang == "uk" else "Played: ") + _spoken_san(san, self.lang))
        except Exception as exc:
            return self._error(str(exc))

    def cancel_selection(self) -> dict[str, Any]:
        self.selected_source = None
        return self._ok("Вибір скасовано." if self.lang == "uk" else "Selection cancelled.")

    def undo(self) -> dict[str, Any]:
        if not self._at_history_end():
            return self._error(self._t("review_before_move"))
        if not self.sans:
            return self._error(self._t("undo_none"))
        san = self.board.undo()
        if san is None:
            return self._error(self._t("undo_none"))
        side = self.move_sides.pop()
        self.sans.pop()
        self.redo_meta.append((san, side))
        if len(self.history_fens) > len(self.sans) + 1:
            self.history_fens.pop()
        self.review_cursor = len(self.sans)
        self.selected_source = None
        return self._ok(("Скасовано: " if self.lang == "uk" else "Undone: ") + _spoken_san(san, self.lang))

    def redo(self) -> dict[str, Any]:
        if not self._at_history_end():
            return self._error(self._t("review_before_move"))
        if not self.redo_meta:
            return self._error(self._t("redo_none"))
        san = self.board.redo()
        if san is None:
            self.redo_meta.clear()
            return self._error(self._t("redo_none"))
        meta_san, side = self.redo_meta.pop()
        self.sans.append(meta_san)
        self.move_sides.append(side)
        self.history_fens.append(self.board.fen())
        self.review_cursor = len(self.sans)
        self.selected_source = None
        return self._ok(("Повторено: " if self.lang == "uk" else "Redone: ") + _spoken_san(meta_san, self.lang))

    def set_turn(self, color: str) -> dict[str, Any]:
        if not self._at_history_end():
            return self._error(self._t("review_before_move"))
        if color not in ("w", "b"):
            return self._error("Неправильний колір." if self.lang == "uk" else "Invalid color.")
        self.board.turn = color
        self.selected_source = None
        self.history_fens[-1] = self.board.fen()
        return self._ok(self._t("white_turn") if color == "w" else self._t("black_turn"))

    def set_fen(self, fen: str) -> dict[str, Any]:
        try:
            self.board = Board(fen)
            self.start_fen = self.board.fen()
            self._reset_history()
            return self._ok("FEN завантажено." if self.lang == "uk" else "FEN loaded.")
        except Exception as exc:
            return self._error(str(exc))

    def set_language(self, lang: str) -> dict[str, Any]:
        if lang not in ("uk", "en"):
            return self._error("Unsupported language")
        self.lang = lang
        return self._ok("Мову змінено." if lang == "uk" else "Language changed.")

    def diagnostic(self) -> dict[str, Any]:
        test = Board()
        test.push_text("e4")
        label_empty = self.square_label("e4") if self.board.board[parse_sq("e4")] else "e 4"
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
            "emptySquareCoordinateOnly": "," not in label_empty if not self.board.board[parse_sq("e4")] else True,
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
