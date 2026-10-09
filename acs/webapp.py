from __future__ import annotations

"""Accessible WebView2 presentation layer for Accessible Chess.

The 0.3.x Tkinter surface failed the first real NVDA acceptance test. This
module keeps the chess core in Python but renders the user-facing document as
semantic HTML inside Edge/WebView2 on Windows. The HTML document is intended
to be consumed by NVDA browse/focus mode rather than by a self-voicing GUI.
"""

from pathlib import Path
import copy
import json
import re
import sys
from typing import Any

from .chesscore import Board, parse_sq, sq_name, color_of
from .history import HistoryError, ReviewHistory
from .input_limits import MAX_FEN_CHARS
from .move_entry import MAX_MOVE_ENTRY_CHARS
from .notation import format_accessible_compact_san, format_san
from .position_text import parse_position_text
from .ui_review_adapter import ReviewPresentationAdapter
from .ai_provider_gateway import AIProviderError, AIProviderGateway, ProviderProfile, ProviderRequest

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
        self.ai_gateway = AIProviderGateway()
        self._ai_settings_owner: Any | None = None
        self.video_sync_active = False
        self.video_sync_last_timecode = 0.0
        self.video_sync_last_confidence = 0.0
        self.video_prepare_active = False
        self.video_prepare_board = Board()
        self.video_timeline: list[dict[str, Any]] = []
        self._video_session_memory: dict[str, dict[str, Any]] = {}
        self._visual_profile_memory = {"profile": "classic", "theme": "system", "board_theme": "wood", "density": "comfortable"}

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

    def _game_status(self, board: Board | None = None) -> str:
        b = board or self._display_board()
        turn_text = self._t("white_turn") if b.turn == "w" else self._t("black_turn")
        if not self._position_complete(b):
            return f"{self._t('setup_incomplete')} {turn_text}"
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
        # Candidate validation is complete. Publish its fields into the stable
        # Board owner so engine/UI adapters that hold the canonical object do
        # not become stale after a move, undo or redo.
        current_board = self.board
        current_board.__dict__.clear()
        current_board.__dict__.update(copy.deepcopy(candidate_board.__dict__))
        self.board = current_board
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
        state = {
            "version": VERSION, "lang": self.lang, "mode": self.mode,
            "gameInfo": status,
            "moves": self._moves_text(),
            "whitePieces": self._pieces_text("w", display_board),
            "blackPieces": self._pieces_text("b", display_board),
            "gameStatus": status, "lastMove": last, "announcement": self.announcement,
            "fen": display_view.fen, "board": self._board_cells(display_board),
            "selectedSquare": (
                sq_name(self.selected_source)
                if self.selected_source is not None and self._at_history_end() else None
            ),
            "engineEnabled": self.engine_enabled, "engineStatus": engine_status,
            "positionComplete": self._position_complete(display_board),
            "reviewCursor": display_view.ply, "historyLength": len(self.sans),
            "reviewStatus": display_view.status, "atHistoryEnd": self._at_history_end(),
        }
        state["videoSync"] = {
            "active": self.video_sync_active,
            "prepared": bool(self.video_timeline),
            "preparing": self.video_prepare_active,
            "timecode": self._video_time_for_ply(display_view.ply),
            "confidence": self.video_sync_last_confidence,
            "timelineLength": len(self.video_timeline),
        }
        return state

    def ai_provider_profiles(self) -> list[dict[str, Any]]:
        """Return editable provider metadata without exposing credential values."""
        self._ensure_ai_profiles_loaded()
        return self.ai_gateway.profiles_for_editor()

    def _ensure_ai_profiles_loaded(self) -> None:
        settings = getattr(self, "_settings", None)
        if settings is None or settings is self._ai_settings_owner:
            return
        self._ai_settings_owner = settings
        try:
            stored = json.loads(settings.get("ai_profiles_json", "{}"))
            if not isinstance(stored, dict):
                return
            for name, raw in stored.items():
                if not isinstance(name, str) or not isinstance(raw, dict):
                    continue
                self.ai_gateway.upsert_profile(ProviderProfile(
                    name=name,
                    base_url=str(raw.get("base_url", "")),
                    model=str(raw.get("model", "")),
                    api_key_env=str(raw.get("api_key_env", "")),
                    protocol=str(raw.get("protocol", "openai-chat")),
                    enabled=bool(raw.get("enabled", True)),
                    timeout_seconds=float(raw.get("timeout_seconds", 30.0)),
                ))
        except (TypeError, ValueError, json.JSONDecodeError):
            return

    def _persist_ai_profiles(self) -> None:
        settings = getattr(self, "_settings", None)
        if settings is None:
            return
        payload = {}
        for item in self.ai_gateway.profiles_for_editor():
            payload[item["name"]] = {
                "base_url": item["base_url"],
                "model": item["model"],
                "api_key_env": item["api_key_env"],
                "protocol": item["protocol"],
                "enabled": item["enabled"],
                "timeout_seconds": item["timeout_seconds"],
            }
        settings.set("ai_profiles_json", json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))

    def ai_update_profile(self, name: str, base_url: str, model: str, api_key_env: str, protocol: str | None = None, timeout_seconds: float | None = None) -> dict[str, Any]:
        """Update a provider profile in the current session; secrets stay in env vars."""
        try:
            self._ensure_ai_profiles_loaded()
            if not all(type(value) is str for value in (name, base_url, model, api_key_env)) or (protocol is not None and type(protocol) is not str):
                raise ValueError("Provider profile fields must be text")
            current = next((item for item in self.ai_gateway.profiles_for_editor() if item["name"] == name), None)
            selected_protocol = protocol.strip() if protocol is not None else str(current.get("protocol", "openai-chat") if current else "openai-chat")
            profile = ProviderProfile(
                name=name.strip(), base_url=base_url.strip(), model=model.strip(),
                api_key_env=api_key_env.strip(), enabled=True,
                protocol=selected_protocol,
                timeout_seconds=float(timeout_seconds if timeout_seconds is not None else (current.get("timeout_seconds", 30.0) if current else 30.0)),
            )
            self.ai_gateway.upsert_profile(profile)
            self._persist_ai_profiles()
            return {"ok": True, "profiles": self.ai_provider_profiles(), "announcement": "AI provider profile updated." if self.lang == "en" else "Профіль AI-провайдера оновлено."}
        except (ValueError, TypeError, OSError):
            return {"ok": False, "profiles": self.ai_provider_profiles(), "announcement": "Invalid AI provider profile." if self.lang == "en" else "Некоректний профіль AI-провайдера."}

    def ai_complete(self, profile_name: str, messages: list[dict[str, str]], temperature: float = 0.2, max_tokens: int = 512) -> dict[str, Any]:
        """Run an optional agent completion through the selected provider."""
        try:
            if type(profile_name) is not str or not isinstance(messages, list) or not messages:
                raise ValueError
            clean = tuple({"role": str(item["role"]), "content": str(item["content"])} for item in messages if isinstance(item, dict) and "role" in item and "content" in item)
            if not clean:
                raise ValueError
            result = self.ai_gateway.complete(profile_name, ProviderRequest(clean, temperature=temperature, max_tokens=max_tokens))
            return {"ok": True, "text": result.text, "provider": result.provider, "model": result.model, "usage": dict(result.usage)}
        except (AIProviderError, ValueError, TypeError):
            return {"ok": False, "announcement": "AI provider request could not be completed." if self.lang == "en" else "Не вдалося виконати запит до AI-провайдера."}

    @staticmethod
    def _video_move_changed_squares(move) -> list[int]:
        changed = {move.frm, move.to}
        if move.castle:
            rook_from, rook_to = {6: (7, 5), 2: (0, 3), 62: (63, 61), 58: (56, 59)}[move.to]
            changed.update((rook_from, rook_to))
        if move.en_passant:
            changed.add(move.to - 8 if move.to > move.frm else move.to + 8)
        return sorted(changed)

    @staticmethod
    def _video_candidates_for_board(board: Board) -> list[dict[str, Any]]:
        candidates = []
        for move in board.legal_moves():
            candidates.append({
                "uci": sq_name(move.frm) + sq_name(move.to) + (move.promotion.lower() if move.promotion else ""),
                "san": board.san(move),
                "fromSquare": move.frm,
                "toSquare": move.to,
                "changedSquares": AccessibleChessAPI._video_move_changed_squares(move),
            })
        return candidates

    def _video_time_for_ply(self, ply: int) -> float:
        if ply <= 0 or not self.video_timeline:
            return 0.0
        index = min(ply, len(self.video_timeline)) - 1
        return float(self.video_timeline[index]["timecode"])

    def video_sync_start(self) -> dict[str, Any]:
        """Reset to the standard position and start deterministic video move sync."""
        state = self.new_game()
        if not state.get("ok"):
            return state
        self.video_sync_active = True
        self.video_sync_last_timecode = 0.0
        self.video_sync_last_confidence = 0.0
        self.video_timeline = []
        state["videoSync"] = {"active": True, "timecode": 0.0, "confidence": 0.0}
        state["candidates"] = self.video_sync_candidates().get("candidates", [])
        return state

    def video_sync_candidates(self) -> dict[str, Any]:
        if not self.video_sync_active:
            return {"ok": False, "candidates": [], "announcement": "Video synchronization is not active." if self.lang == "en" else "Синхронізація відео не активна."}
        candidates = self._video_candidates_for_board(self.board)
        return {"ok": True, "candidates": candidates, "fen": self.board.fen()}

    def video_sync_commit_move(self, uci: str, timecode: float, confidence: float) -> dict[str, Any]:
        if not self.video_sync_active:
            return self._error("Video synchronization is not active." if self.lang == "en" else "Синхронізація відео не активна.")
        try:
            seconds = float(timecode)
            score = float(confidence)
            if not 0.0 <= seconds <= 24 * 60 * 60 or not 0.0 <= score <= 1.0 or seconds < self.video_sync_last_timecode:
                raise ValueError
            move = self.board.parse_move(uci)
        except (TypeError, ValueError):
            return self._error("The recognized video move is invalid." if self.lang == "en" else "Розпізнаний хід із відео некоректний.")
        result = self.make_move(sq_name(move.frm) + sq_name(move.to) + (move.promotion.lower() if move.promotion else ""))
        if result.get("ok"):
            self.video_sync_last_timecode = seconds
            self.video_sync_last_confidence = score
            self.video_timeline.append({"ply": len(self.video_timeline) + 1, "uci": uci, "san": self.sans[-1], "timecode": seconds, "confidence": score})
            result["videoSync"] = {"active": True, "timecode": seconds, "confidence": score}
            result["candidates"] = self.video_sync_candidates().get("candidates", [])
        return result

    def video_prepare_start(self) -> dict[str, Any]:
        """Start an isolated fast scan without moving the user-visible board."""
        self.video_prepare_board = Board()
        self.video_timeline = []
        self.video_prepare_active = True
        return {
            "ok": True,
            "candidates": self._video_candidates_for_board(self.video_prepare_board),
            "fen": self.video_prepare_board.fen(),
            "timelineLength": 0,
        }

    def video_prepare_candidates(self) -> dict[str, Any]:
        if not self.video_prepare_active:
            return {"ok": False, "candidates": []}
        return {
            "ok": True,
            "candidates": self._video_candidates_for_board(self.video_prepare_board),
            "fen": self.video_prepare_board.fen(),
        }

    def video_prepare_commit_move(self, uci: str, timecode: float, confidence: float) -> dict[str, Any]:
        if not self.video_prepare_active:
            return {"ok": False, "candidates": []}
        try:
            seconds = float(timecode)
            score = float(confidence)
            last_time = float(self.video_timeline[-1]["timecode"]) if self.video_timeline else 0.0
            if not 0.0 <= seconds <= 24 * 60 * 60 or seconds < last_time or not 0.0 <= score <= 1.0:
                raise ValueError
            move = self.video_prepare_board.parse_move(uci)
            san = self.video_prepare_board.san(move)
            self.video_prepare_board.push(move)
        except (TypeError, ValueError):
            return {"ok": False, "candidates": []}
        self.video_timeline.append({
            "ply": len(self.video_timeline) + 1,
            "uci": uci,
            "san": san,
            "timecode": seconds,
            "confidence": score,
        })
        return {
            "ok": True,
            "candidates": self._video_candidates_for_board(self.video_prepare_board),
            "fen": self.video_prepare_board.fen(),
            "timelineLength": len(self.video_timeline),
        }

    def video_prepare_finish(self) -> dict[str, Any]:
        """Publish the prepared game once, then show its starting position."""
        if not self.video_prepare_active:
            return self._error("Video preparation is not active." if self.lang == "en" else "Підготовка відео не активна.")
        prepared = [dict(item) for item in self.video_timeline]
        self.video_prepare_active = False
        state = self.new_game()
        if not state.get("ok"):
            return state
        for item in prepared:
            state = self.make_move(str(item["uci"]))
            if not state.get("ok"):
                self.video_timeline = []
                return self._error("Prepared video timeline is invalid." if self.lang == "en" else "Підготовлена шкала відео некоректна.")
        self.video_timeline = prepared
        self.video_sync_active = True
        self.video_sync_last_timecode = float(prepared[-1]["timecode"]) if prepared else 0.0
        self.video_sync_last_confidence = float(prepared[-1]["confidence"]) if prepared else 0.0
        state = self.go_to_move("0")
        state["timeline"] = prepared
        state["announcement"] = (
            f"Video prepared: {len(prepared)} moves recognized."
            if self.lang == "en" else f"Відео підготовлено: розпізнано {len(prepared)} ходів."
        )
        return state

    def video_prepare_cancel(self) -> dict[str, Any]:
        self.video_prepare_active = False
        self.video_prepare_board = Board()
        self.video_timeline = []
        return {"ok": True, "timelineLength": 0}

    def video_sync_load_timeline(self, timeline: list[dict[str, Any]]) -> dict[str, Any]:
        """Validate and activate a previously prepared in-memory video session."""
        if not isinstance(timeline, list) or len(timeline) > 4096:
            return self._error("Invalid video timeline." if self.lang == "en" else "Некоректна шкала відео.")
        self.video_prepare_start()
        for raw in timeline:
            if not isinstance(raw, dict):
                self.video_prepare_cancel()
                return self._error("Invalid video timeline." if self.lang == "en" else "Некоректна шкала відео.")
            result = self.video_prepare_commit_move(raw.get("uci"), raw.get("timecode"), raw.get("confidence"))
            if not result.get("ok"):
                self.video_prepare_cancel()
                return self._error("Invalid video timeline." if self.lang == "en" else "Некоректна шкала відео.")
        return self.video_prepare_finish()

    def video_sync_seek_time(self, timecode: float) -> dict[str, Any]:
        """Project the prepared history at a playback time without inventing moves."""
        try:
            seconds = float(timecode)
            if not 0.0 <= seconds <= 24 * 60 * 60:
                raise ValueError
        except (TypeError, ValueError):
            return self._error("Invalid video timecode." if self.lang == "en" else "Некоректний час відео.")
        ply = sum(1 for item in self.video_timeline if float(item["timecode"]) <= seconds)
        try:
            lineage = self._live_line_nodes()
            state = self._select_review_node(lineage[min(ply, len(lineage) - 1)])
        except Exception:
            return self._error("Video history is unavailable." if self.lang == "en" else "Історія відео недоступна.")
        state["videoTargetPly"] = ply
        state["videoTargetTimecode"] = seconds
        return state

    def video_sync_timeline(self) -> dict[str, Any]:
        return {"ok": True, "timeline": [dict(item) for item in self.video_timeline]}

    def _video_sessions(self) -> dict[str, dict[str, Any]]:
        settings = getattr(self, "_settings", None)
        if settings is None:
            return {key: dict(value) for key, value in self._video_session_memory.items()}
        try:
            raw = json.loads(settings.get("video_sessions_json", "{}"))
            if not isinstance(raw, dict):
                raise ValueError
            return {str(key): dict(value) for key, value in raw.items() if isinstance(key, str) and isinstance(value, dict)}
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}

    def _store_video_sessions(self, sessions: dict[str, dict[str, Any]]) -> None:
        settings = getattr(self, "_settings", None)
        if settings is None:
            self._video_session_memory = {key: dict(value) for key, value in sessions.items()}
            return
        settings.set("video_sessions_json", json.dumps(sessions, ensure_ascii=False, sort_keys=True, separators=(",", ":")))

    @staticmethod
    def _validated_video_timeline(timeline: Any) -> list[dict[str, Any]]:
        if not isinstance(timeline, list) or len(timeline) > 4096:
            raise ValueError("invalid timeline")
        board = Board()
        result: list[dict[str, Any]] = []
        last_time = 0.0
        for index, raw in enumerate(timeline, start=1):
            if not isinstance(raw, dict):
                raise ValueError("invalid timeline entry")
            uci = raw.get("uci")
            seconds = float(raw.get("timecode"))
            confidence = float(raw.get("confidence"))
            if type(uci) is not str or len(uci) not in {4, 5} or seconds < last_time or not 0 <= seconds <= 86400 or not 0 <= confidence <= 1:
                raise ValueError("invalid timeline entry")
            move = board.parse_move(uci)
            san = board.san(move)
            board.push(move)
            result.append({"ply": index, "uci": uci, "san": san, "timecode": seconds, "confidence": confidence})
            last_time = seconds
        return result

    def video_session_list(self) -> dict[str, Any]:
        sessions = self._video_sessions()
        items = []
        for session_id, entry in sorted(sessions.items(), key=lambda item: str(item[1].get("name", "")).casefold()):
            timeline = entry.get("timeline")
            items.append({
                "id": session_id,
                "name": str(entry.get("name", "Video"))[:240],
                "duration": float(entry.get("duration", 0.0)),
                "moves": len(timeline) if isinstance(timeline, list) else 0,
            })
        return {"ok": True, "sessions": items}

    def video_session_save(self, session_id: str, name: str, duration: float, timeline: list[dict[str, Any]]) -> dict[str, Any]:
        try:
            if type(session_id) is not str or not session_id or len(session_id) > 512 or type(name) is not str or not name.strip() or len(name) > 240:
                raise ValueError
            seconds = float(duration)
            if not 0 < seconds <= 86400:
                raise ValueError
            canonical = self._validated_video_timeline(timeline)
            sessions = self._video_sessions()
            sessions[session_id] = {"name": name.strip(), "duration": seconds, "timeline": canonical}
            if len(sessions) > 32:
                oldest = next(iter(sessions))
                if oldest != session_id:
                    sessions.pop(oldest, None)
            self._store_video_sessions(sessions)
            return {"ok": True, "id": session_id, "moves": len(canonical)}
        except (TypeError, ValueError, OverflowError, OSError):
            return {"ok": False}

    def video_session_get(self, session_id: str) -> dict[str, Any]:
        if type(session_id) is not str:
            return {"ok": False}
        entry = self._video_sessions().get(session_id)
        if not entry:
            return {"ok": False}
        try:
            timeline = self._validated_video_timeline(entry.get("timeline"))
        except (TypeError, ValueError, OverflowError):
            return {"ok": False}
        return {"ok": True, "id": session_id, "name": str(entry.get("name", "Video"))[:240], "duration": float(entry.get("duration", 0.0)), "timeline": timeline}

    def visual_profile_get(self) -> dict[str, Any]:
        settings = getattr(self, "_settings", None)
        if settings is None:
            values = dict(self._visual_profile_memory)
        else:
            try:
                values = json.loads(settings.get("visual_profile_json"))
            except (TypeError, ValueError, json.JSONDecodeError):
                values = dict(self._visual_profile_memory)
        return {"ok": True, **values}

    def visual_profile_apply(self, profile: str, theme: str, board_theme: str, density: str) -> dict[str, Any]:
        allowed = {
            "profile": {"classic", "studio", "tournament", "low-vision", "minimal"},
            "theme": {"system", "light", "dark", "contrast"},
            "board_theme": {"wood", "graphite", "blue", "minimal", "high-contrast"},
            "density": {"comfortable", "compact", "spacious"},
        }
        values = {"profile": profile, "theme": theme, "board_theme": board_theme, "density": density}
        if any(type(value) is not str or value not in allowed[key] for key, value in values.items()):
            return {"ok": False}
        payload = json.dumps(values, sort_keys=True, separators=(",", ":"))
        settings = getattr(self, "_settings", None)
        try:
            if settings is None:
                self._visual_profile_memory = dict(values)
            else:
                settings.set("visual_profile_json", payload)
        except (TypeError, ValueError, OSError):
            return {"ok": False}
        return {"ok": True, **values, "announcement": "Visual profile applied." if self.lang == "en" else "Візуальний профіль застосовано."}

    def visual_profile_export(self) -> dict[str, Any]:
        """Manual Windows/Web transfer; existing Settings remains sole native writer."""
        from .visual_profile_transfer import (
            VisualProfileTransferError, encode_transfer, revision_of_stored_text,
        )

        settings = getattr(self, "_settings", None)
        if settings is None:
            return {"ok": False, "reason": "settings_unavailable"}
        if str(getattr(settings, "warning", "")).startswith("settings recovery:"):
            return {"ok": False, "reason": "settings_recovery_required"}
        try:
            raw = settings.get("visual_profile_json")
            revision = revision_of_stored_text(raw)
            values = json.loads(raw)
            return {"ok": True, "payload": encode_transfer(values), "revision": revision}
        except (VisualProfileTransferError, TypeError, ValueError, UnicodeError):
            return {"ok": False, "reason": "invalid_stored_profile"}

    def visual_profile_import(self, payload: str, expected_revision: str) -> dict[str, Any]:
        """Explicit import with stale-revision rejection and atomic Settings CAS."""
        import re
        from .visual_profile_transfer import (
            VisualProfileTransferError, decode_transfer, revision_of_stored_text,
        )

        settings = getattr(self, "_settings", None)
        if settings is None:
            return {"ok": False, "reason": "settings_unavailable"}
        if str(getattr(settings, "warning", "")).startswith("settings recovery:"):
            return {"ok": False, "reason": "settings_recovery_required"}
        if type(expected_revision) is not str or re.fullmatch(r"[0-9a-f]{64}", expected_revision) is None:
            return {"ok": False, "reason": "invalid_revision"}
        try:
            # Validate the *entire* payload before touching mutable state.
            preferences = decode_transfer(payload)
            current = settings.get("visual_profile_json")
            if revision_of_stored_text(current) != expected_revision:
                return {"ok": False, "reason": "stale_revision"}
            settings.set(
                "visual_profile_json",
                json.dumps(preferences, sort_keys=True, separators=(",", ":")),
            )
            updated = self.visual_profile_export()
            if not updated.get("ok"):
                return {"ok": False, "reason": "readback_failed"}
            return {
                "ok": True,
                **preferences,
                "revision": updated["revision"],
                "announcement": "Visual profile imported." if self.lang == "en"
                else "Візуальний профіль імпортовано.",
            }
        except (VisualProfileTransferError, TypeError, ValueError, OSError, UnicodeError):
            return {"ok": False, "reason": "import_rejected"}

    def video_sync_stop(self) -> dict[str, Any]:
        self.video_sync_active = False
        state = self.get_state()
        state["ok"] = True
        state["videoSync"] = {"active": False, "timecode": self.video_sync_last_timecode, "confidence": self.video_sync_last_confidence}
        state["announcement"] = "Video synchronization stopped." if self.lang == "en" else "Синхронізацію відео зупинено."
        return state

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
            candidate_board = copy.deepcopy(self.board)
            candidate_board.turn = color
            prepared = self._prepare_root_state(candidate_board)
        except Exception:
            return self._error(self._t("editor_history_failed"))
        # Changing side-to-move is an editor operation, so the edited position
        # becomes a new live root rather than rewriting an immutable history node.
        self._publish_root_state(candidate_board, prepared)
        return self._ok(self._t("white_turn") if color == "w" else self._t("black_turn"))

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
