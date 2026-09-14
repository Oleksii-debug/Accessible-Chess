"""WebView-facing Teacher/Classroom visual projection over canonical state.

DEV1 owns projection, focus/keyboard semantics and bounded NVDA feedback.
Authoritative pointer/highlight/arrow/permission state remains external and is
read through :class:`TeacherPresentationState`.  Sighted-board pieces may be
read either through a narrow FEN provider or, preferably, one canonical
:class:`TeachingSessionState` provider.  The projection never stores or mutates
chess state and never returns raw FEN.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from .chesscore import Board, PIECE_UA
from .squares import square_name
from .teacher_presentation import (
    BoardOrientation,
    StudentEventKind,
    TeacherPresentationState,
)
from .teaching_session import TeachingSessionState

_ALLOWED_PERMISSIONS = frozenset({"locked", "select_only", "move_allowed"})
_ALLOWED_ENGINE_VISIBILITY = frozenset(
    {"visible_to_teacher", "visible_to_student", "hidden"}
)
_PIECE_GLYPHS = {
    "K": "♔",
    "Q": "♕",
    "R": "♖",
    "B": "♗",
    "N": "♘",
    "P": "♙",
    "k": "♚",
    "q": "♛",
    "r": "♜",
    "b": "♝",
    "n": "♞",
    "p": "♟",
}
_PIECE_EN = {
    "P": "white pawn",
    "N": "white knight",
    "B": "white bishop",
    "R": "white rook",
    "Q": "white queen",
    "K": "white king",
    "p": "black pawn",
    "n": "black knight",
    "b": "black bishop",
    "r": "black rook",
    "q": "black queen",
    "k": "black king",
}


@dataclass(frozen=True, slots=True)
class TeacherWebViewEvent:
    kind: str
    payload: Mapping[str, object]


class TeacherWebViewProjection:
    """JSON-ready Teacher board projection without owning canonical state."""

    def __init__(
        self,
        teacher: TeacherPresentationState,
        *,
        position_fen_provider: Callable[[], str] | None = None,
        teaching_state_provider: Callable[[], TeachingSessionState] | None = None,
    ) -> None:
        if not isinstance(teacher, TeacherPresentationState):
            raise TypeError("teacher must be TeacherPresentationState")
        if position_fen_provider is not None and not callable(position_fen_provider):
            raise TypeError("position_fen_provider must be callable or None")
        if teaching_state_provider is not None and not callable(teaching_state_provider):
            raise TypeError("teaching_state_provider must be callable or None")
        if position_fen_provider is not None and teaching_state_provider is not None:
            raise ValueError("choose one canonical teaching-position provider")
        self._teacher = teacher
        self._position_fen_provider = position_fen_provider
        self._teaching_state_provider = teaching_state_provider

    @classmethod
    def from_teaching_session(
        cls,
        dispatch: Callable[[str, Mapping[str, object]], object],
        state_provider: Callable[[], TeachingSessionState],
        *,
        feedback_limit: int = 50,
    ) -> "TeacherWebViewProjection":
        """Compose the WebView surface directly over canonical teaching state.

        The application still owns state mutation. ``dispatch`` must route stable
        action IDs to that application boundary; this helper only adapts the
        immutable canonical state for presentation and guarantees that one
        ``snapshot()`` uses one teaching-state revision for pieces and overlays.
        """

        if not callable(dispatch):
            raise TypeError("teacher presentation dispatcher must be callable")
        if not callable(state_provider):
            raise TypeError("teaching_state_provider must be callable")

        def presentation_provider() -> Mapping[str, object]:
            state = cls._read_teaching_state(state_provider)
            return cls._presentation_mapping(state)

        teacher = TeacherPresentationState(
            dispatch,
            presentation_provider,
            feedback_limit=feedback_limit,
        )
        return cls(teacher, teaching_state_provider=state_provider)

    @staticmethod
    def _read_teaching_state(
        provider: Callable[[], TeachingSessionState],
    ) -> TeachingSessionState:
        state = provider()
        if type(state) is not TeachingSessionState:
            raise TypeError("canonical teaching state provider must return TeachingSessionState")
        return state

    @staticmethod
    def _presentation_mapping(state: TeachingSessionState) -> dict[str, object]:
        presentation = state.presentation
        return {
            "pointer_square": presentation.pointer.square,
            "highlights": tuple(
                {"square": item.square, "purpose": item.purpose}
                for item in presentation.highlights
            ),
            "arrows": tuple(
                {
                    "start_square": item.start_square,
                    "end_square": item.end_square,
                    "purpose": item.purpose,
                }
                for item in presentation.arrows
            ),
            "coordinates_visible": presentation.coordinate_labels_visible,
            "board_permission": presentation.board_permission.value,
            "engine_visibility": presentation.engine_visibility.value,
        }

    @staticmethod
    def _visual_cell(square: str, orientation: BoardOrientation) -> dict[str, int]:
        file_index = ord(square[0]) - ord("a")
        rank_index = int(square[1]) - 1
        if orientation is BoardOrientation.WHITE:
            row = 8 - rank_index
            column = file_index + 1
        else:
            row = rank_index + 1
            column = 8 - file_index
        return {"row": row, "column": column}

    def _square_item(
        self,
        square: object,
        *,
        purpose: object = "custom",
    ) -> dict[str, object]:
        normalized = self._teacher.normalize_square(square)
        token = str(purpose or "custom").strip().lower()
        style = self._teacher.style(token)
        return {
            "square": normalized,
            "purpose": style.purpose,
            "color": style.color,
            "cell": self._visual_cell(normalized, self._teacher.orientation),
        }

    def _piece_items(
        self,
        *,
        language: str,
        fen: str | None,
    ) -> tuple[dict[str, object], ...]:
        if fen is None:
            return ()
        if type(fen) is not str:
            raise TypeError("canonical teaching position provider must return FEN text")
        board = Board(fen)
        names = _PIECE_EN if language == "en" else PIECE_UA
        result: list[dict[str, object]] = []
        for index, piece in enumerate(board.board):
            if piece is None:
                continue
            square = square_name(index)
            result.append(
                {
                    "square": square,
                    "symbol": piece,
                    "glyph": _PIECE_GLYPHS[piece],
                    "name": names[piece],
                    "cell": self._visual_cell(square, self._teacher.orientation),
                }
            )
        return tuple(result)

    @staticmethod
    def _accessible_summary(
        *,
        pointer: Mapping[str, object] | None,
        highlights: tuple[Mapping[str, object], ...],
        arrows: tuple[Mapping[str, object], ...],
        language: str,
    ) -> str:
        parts: list[str] = []
        if pointer is not None:
            square = str(pointer["square"])
            parts.append(f"Pointer {square}" if language == "en" else f"Вказівник {square}")
        if highlights:
            body = ", ".join(
                f"{item['square']} {item['purpose']}" for item in highlights
            )
            parts.append(
                f"Highlights: {body}"
                if language == "en"
                else f"Підсвічування: {body}"
            )
        if arrows:
            body = ", ".join(
                f"{item['start_square']}–{item['end_square']} {item['purpose']}"
                for item in arrows
            )
            parts.append(f"Arrows: {body}" if language == "en" else f"Стрілки: {body}")
        if not parts:
            return "No teaching annotations." if language == "en" else "Навчальних позначок немає."
        return ". ".join(parts) + "."

    def snapshot(self, *, language: str = "uk") -> dict[str, object]:
        # The canonical TeachingSession path reads exactly one immutable state
        # revision, so pieces and presentation overlays cannot tear across
        # concurrent session updates.
        if self._teaching_state_provider is not None:
            teaching_state = self._read_teaching_state(self._teaching_state_provider)
            state = self._presentation_mapping(teaching_state)
            fen: str | None = teaching_state.position_fen
        else:
            state = self._teacher.snapshot()
            fen = None
            if self._position_fen_provider is not None:
                fen = self._position_fen_provider()
        lang = "en" if str(language).lower() == "en" else "uk"

        pointer = state.get("pointer_square")
        pointer_item = None
        if pointer:
            pointer_item = self._square_item(pointer, purpose="selected")

        highlights: list[dict[str, object]] = []
        for item in state.get("highlights") or ():
            if not isinstance(item, Mapping):
                raise ValueError("invalid teacher highlight state")
            highlights.append(
                self._square_item(
                    item.get("square"),
                    purpose=item.get("purpose") or "custom",
                )
            )

        arrows: list[dict[str, object]] = []
        for item in state.get("arrows") or ():
            if not isinstance(item, Mapping):
                raise ValueError("invalid teacher arrow state")
            start = self._square_item(
                item.get("start_square"),
                purpose=item.get("purpose") or "custom",
            )
            end = self._square_item(
                item.get("end_square"),
                purpose=item.get("purpose") or "custom",
            )
            if start["square"] == end["square"]:
                raise ValueError("invalid zero-length teacher arrow state")
            arrows.append(
                {
                    "start_square": start["square"],
                    "end_square": end["square"],
                    "purpose": start["purpose"],
                    "color": start["color"],
                    "start_cell": start["cell"],
                    "end_cell": end["cell"],
                }
            )

        permission = str(state.get("board_permission") or "locked").strip().lower()
        if permission not in _ALLOWED_PERMISSIONS:
            raise ValueError("invalid teacher board permission state")
        engine_visibility = str(
            state.get("engine_visibility") or "hidden"
        ).strip().lower()
        if engine_visibility not in _ALLOWED_ENGINE_VISIBILITY:
            raise ValueError("invalid teacher engine visibility state")

        coordinates_visible = state.get("coordinates_visible", True)
        if type(coordinates_visible) is not bool:
            raise ValueError("invalid teacher coordinates state")

        highlight_items = tuple(highlights)
        arrow_items = tuple(arrows)
        piece_items = self._piece_items(language=lang, fen=fen)
        return {
            "board": {
                "orientation": self._teacher.orientation.value,
                "coordinates_visible": coordinates_visible,
                "permission": permission,
                "engine_visibility": engine_visibility,
            },
            "pieces": piece_items,
            "pointer": pointer_item,
            "highlights": highlight_items,
            "arrows": arrow_items,
            "mode": self._teacher.teaching_mode.value,
            "accessible_summary": self._accessible_summary(
                pointer=pointer_item,
                highlights=highlight_items,
                arrows=arrow_items,
                language=lang,
            ),
            "feedback": tuple(
                self._teacher.concise_student_event(event, language=lang)
                for event in self._teacher.feedback_events(limit=10)
            ),
        }

    def type_pointer_text(self, text: str) -> TeacherWebViewEvent:
        value = str(text)
        if len(value) != 2:
            raise ValueError("teacher pointer coordinate must contain two characters")
        dispatched = None
        for character in value:
            dispatched = self._teacher.type_pointer_character(character)
        return TeacherWebViewEvent(
            "pointer-input",
            {"square": dispatched or "", "clear_editor": True},
        )

    def toggle_orientation(self) -> TeacherWebViewEvent:
        orientation = self._teacher.toggle_orientation()
        return TeacherWebViewEvent(
            "render",
            {"orientation": orientation.value, "snapshot": self.snapshot()},
        )

    def record_student_event(
        self,
        kind: str,
        square: str,
        *,
        piece_name: str = "",
        student_id: str = "",
        sequence: int | None = None,
        language: str = "uk",
    ) -> TeacherWebViewEvent:
        try:
            parsed = StudentEventKind(str(kind).strip().lower())
        except ValueError:
            raise ValueError("unsupported student event kind") from None
        event = self._teacher.record_student_event(
            parsed,
            square,
            piece_name=piece_name,
            student_id=student_id,
            sequence=sequence,
        )
        # Hover updates the visual/history channel but never live-announces: rapid
        # mouse movement must not flood NVDA. Explicit selection may announce once.
        announcement = (
            self._teacher.concise_student_event(event, language=language)
            if parsed is StudentEventKind.SELECT
            else ""
        )
        return TeacherWebViewEvent(
            "student-event",
            {
                "event_kind": parsed.value,
                "square": event.square,
                "announcement": announcement,
                "live_region": bool(announcement),
            },
        )
