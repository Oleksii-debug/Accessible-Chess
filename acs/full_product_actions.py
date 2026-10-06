"""Full-product action catalog and routing bridge.

The existing :mod:`acs.keybindings` registry remains the single keyboard/action
authority. This module only extends that registry with full-product presentation
commands and delegates domain work to the application command dispatcher.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .full_product_ui_shell import AccessibleShellState, ROUTES, UILanguage
from .keybindings import ActionDefinition, ActionRegistry, BindingContext, DEFAULT_ACTIONS


def _action(
    action_id: str,
    context: BindingContext,
    title: str,
    binding: str | None = None,
    description: str = "",
) -> ActionDefinition:
    return ActionDefinition(
        action_id,
        context,
        title,
        binding,
        description=description,
    )


FULL_PRODUCT_ACTIONS: tuple[ActionDefinition, ...] = (
    *(
        _action(
            route.open_action_id,
            BindingContext.GLOBAL,
            route.heading[UILanguage.EN],
            binding="F1" if route.open_action_id == "screen.help" else None,
        )
        for route in ROUTES
    ),
    _action("pgn.open", BindingContext.DOCUMENT, "Open PGN"),
    _action("pgn.cancel_open", BindingContext.DOCUMENT, "Cancel PGN Open"),
    _action("pgn.save", BindingContext.DOCUMENT, "Save PGN"),
    _action("pgn.save_as", BindingContext.DOCUMENT, "Save PGN As"),
    _action("pgn.new_from_position", BindingContext.BOARD, "Create PGN from current position"),
    _action("pgn.cancel_save", BindingContext.DOCUMENT, "Cancel PGN Save"),
    _action("pgn.open_on_board", BindingContext.DOCUMENT, "Review PGN on board"),
    _action("pgn.return", BindingContext.DOCUMENT, "Return to PGN"),
    _action("pgn.board_next_move", BindingContext.DOCUMENT, "Next PGN board move"),
    _action("pgn.board_previous_move", BindingContext.DOCUMENT, "Previous PGN board move"),
    _action("pgn.board_enter_variation", BindingContext.DOCUMENT, "Enter PGN board variation"),
    _action("pgn.board_leave_variation", BindingContext.DOCUMENT, "Leave PGN board variation"),
    _action("pgn.select_item", BindingContext.DOCUMENT, "Select GameTree item"),
    _action("pgn.previous_game", BindingContext.DOCUMENT, "Previous PGN game"),
    _action("pgn.next_game", BindingContext.DOCUMENT, "Next PGN game"),
    _action("pgn.search", BindingContext.DOCUMENT, "Search PGN"),
    _action("pgn.previous_item", BindingContext.PGN_TREE, "Previous GameTree item", "Up"),
    _action("pgn.next_item", BindingContext.PGN_TREE, "Next GameTree item", "Down"),
    _action("pgn.parent_variation", BindingContext.PGN_TREE, "Return to parent variation", "Left"),
    _action("pgn.first_child", BindingContext.PGN_TREE, "First child GameTree item", "Right"),
    _action("pgn.first_item", BindingContext.PGN_TREE, "First GameTree item", "Home"),
    _action("pgn.last_item", BindingContext.PGN_TREE, "Last GameTree item", "End"),
    _action("pgn.comment_edit", BindingContext.DOCUMENT, "Add or edit GameTree comment"),
    _action("pgn.comment_delete", BindingContext.DOCUMENT, "Delete GameTree comment"),
    _action("pgn.nag_edit", BindingContext.DOCUMENT, "Edit move NAG annotations"),
    _action("pgn.variation_add", BindingContext.DOCUMENT, "Add variation or subvariation"),
    _action("pgn.variation_delete", BindingContext.DOCUMENT, "Delete variation"),
    _action("pgn.variation_promote", BindingContext.DOCUMENT, "Promote variation"),
    _action("pgn.copy_selection", BindingContext.DOCUMENT, "Copy selected game or variation"),
    _action("pgn.export_selection", BindingContext.DOCUMENT, "Export selected game or variation"),
    _action("position.copy_fen", BindingContext.BOARD, "Copy current FEN"),
    _action("library.search", BindingContext.DATABASE, "Search library"),
    _action("library.reset_filters", BindingContext.DATABASE, "Reset library filters"),
    _action("library.next_page", BindingContext.DATABASE, "Next library page"),
    _action("library.previous_page", BindingContext.DATABASE, "Previous library page"),
    _action("library.previous_result", BindingContext.LIBRARY_RESULTS, "Previous library result", "Up"),
    _action("library.next_result", BindingContext.LIBRARY_RESULTS, "Next library result", "Down"),
    _action("library.first_result", BindingContext.LIBRARY_RESULTS, "First library result", "Home"),
    _action("library.last_result", BindingContext.LIBRARY_RESULTS, "Last library result", "End"),
    _action("library.open_game", BindingContext.LIBRARY_RESULTS, "Open selected library game", "Enter"),
    _action("library.import", BindingContext.DATABASE, "Import into library"),
    _action(
        "library.cancel_import",
        BindingContext.GLOBAL,
        "Cancel library operation",
        "Ctrl+Shift+X",
    ),
    _action("library.export", BindingContext.DATABASE, "Export from library"),
    _action("book.open", BindingContext.BOOK_READER, "Open book"),
    _action("book.cancel_open", BindingContext.BOOK_READER, "Cancel book open"),
    _action("book.board_next_move", BindingContext.BOOK_READER, "Next move in book game"),
    _action("book.board_previous_move", BindingContext.BOOK_READER, "Previous move in book game"),
    _action("book.board_enter_variation", BindingContext.BOOK_READER, "Enter book game variation"),
    _action("book.board_leave_variation", BindingContext.BOOK_READER, "Leave book game variation"),
    _action("book.board_analyze", BindingContext.BOOK_READER, "Analyze book position"),
    _action("book.previous_block", BindingContext.BOOK_READER, "Previous book block"),
    _action("book.next_block", BindingContext.BOOK_READER, "Next book block"),
    _action("book.previous_heading", BindingContext.BOOK_READER, "Previous book heading"),
    _action("book.next_heading", BindingContext.BOOK_READER, "Next book heading"),
    _action("book.previous_position", BindingContext.BOOK_READER, "Previous book position"),
    _action("book.next_position", BindingContext.BOOK_READER, "Next book position"),
    _action("book.previous_game", BindingContext.BOOK_READER, "Previous book game"),
    _action("book.next_game", BindingContext.BOOK_READER, "Next book game"),
    _action("book.bookmark", BindingContext.BOOK_READER, "Save book return point"),
    _action("book.open_position", BindingContext.BOOK_READER, "Open book position on board"),
    _action("book.open_game", BindingContext.BOOK_READER, "Open book game on board"),
    _action("book.return", BindingContext.BOOK_READER, "Return to book"),
    _action("training.submit", BindingContext.DOCUMENT, "Submit training answer"),
    _action("training.hint", BindingContext.DOCUMENT, "Training hint"),
    _action("training.reveal_solution", BindingContext.DOCUMENT, "Reveal training solution"),
    _action("training.retry", BindingContext.DOCUMENT, "Retry training step"),
    _action("training.reset", BindingContext.DOCUMENT, "Reset training exercise"),
    _action("teacher.pointer_input", BindingContext.DOCUMENT, "Teacher pointer input", "Ctrl+Alt+P"),
    _action("teacher.pointer_clear", BindingContext.DOCUMENT, "Clear teacher pointer"),
    _action("teacher.highlight", BindingContext.DOCUMENT, "Highlight square"),
    _action("teacher.arrow", BindingContext.DOCUMENT, "Add teaching arrow"),
    _action("teacher.clear_annotations", BindingContext.DOCUMENT, "Clear teaching annotations"),
    _action("teacher.coordinates_toggle", BindingContext.DOCUMENT, "Toggle teaching coordinates"),
    _action("teacher.orientation_toggle", BindingContext.DOCUMENT, "Toggle board orientation"),
    _action("teacher.board_permission", BindingContext.DOCUMENT, "Set student board permission"),
    _action("teacher.engine_visibility", BindingContext.DOCUMENT, "Set teaching engine visibility"),
    _action("teacher.read_student_event", BindingContext.DOCUMENT, "Read latest student event"),
    _action(
        "teacher.prepared_previous",
        BindingContext.DOCUMENT,
        "Previous prepared teaching position",
        "Ctrl+Alt+PageUp",
    ),
    _action(
        "teacher.prepared_next",
        BindingContext.DOCUMENT,
        "Next prepared teaching position",
        "Ctrl+Alt+PageDown",
    ),
    _action(
        "teacher.rotation_start_or_resume",
        BindingContext.DOCUMENT,
        "Start or resume group rotation",
        "Ctrl+Alt+R",
    ),
    _action(
        "teacher.rotation_advance",
        BindingContext.DOCUMENT,
        "Advance group rotation",
        "Ctrl+Alt+N",
    ),
    _action(
        "teacher.rotation_bind_pairing",
        BindingContext.DOCUMENT,
        "Bind current pairings to rotation",
        "Ctrl+Alt+B",
    ),
    _action(
        "teacher.rotation_status",
        BindingContext.DOCUMENT,
        "Read group rotation status",
        "Ctrl+Alt+S",
    ),
    _action("student.move", BindingContext.DOCUMENT, "Submit explicit student move"),
    _action("education.previous_item", BindingContext.EDUCATION_LIST, "Previous education item", "Up"),
    _action("education.next_item", BindingContext.EDUCATION_LIST, "Next education item", "Down"),
    _action("education.open_selected", BindingContext.EDUCATION_LIST, "Open selected education item", "Enter"),
    _action("classroom.previous_item", BindingContext.CLASSROOM_LIST, "Previous classroom item", "Up"),
    _action("classroom.next_item", BindingContext.CLASSROOM_LIST, "Next classroom item", "Down"),
    _action("classroom.first_item", BindingContext.CLASSROOM_LIST, "First classroom item", "Home"),
    _action("classroom.last_item", BindingContext.CLASSROOM_LIST, "Last classroom item", "End"),
    _action("classroom.open_selected", BindingContext.CLASSROOM_LIST, "Open selected classroom item", "Enter"),
    _action("toolbar.previous_control", BindingContext.TOOLBAR, "Previous toolbar control", "Left"),
    _action("toolbar.next_control", BindingContext.TOOLBAR, "Next toolbar control", "Right"),
    _action("toolbar.first_control", BindingContext.TOOLBAR, "First toolbar control", "Home"),
    _action("toolbar.last_control", BindingContext.TOOLBAR, "Last toolbar control", "End"),
    _action("profile.save_name", BindingContext.PROFILE_DIALOG, "Save local profile name", "Enter"),
    _action("classes.new", BindingContext.DOCUMENT, "New class"),
    _action("classes.open", BindingContext.DOCUMENT, "Open class"),
    _action("classes.student_open", BindingContext.DOCUMENT, "Open student"),
    _action("classes.lesson_open", BindingContext.DOCUMENT, "Open lesson"),
    _action("classes.assignment_open", BindingContext.DOCUMENT, "Open assignment"),
    _action("remote.connect", BindingContext.DOCUMENT, "Connect shared lesson"),
    _action("remote.reconnect", BindingContext.DOCUMENT, "Reconnect shared lesson"),
    _action("remote.leave", BindingContext.DOCUMENT, "Leave shared lesson"),
)


FULL_PRODUCT_ACTION_IDS = frozenset(item.action_id for item in FULL_PRODUCT_ACTIONS)
_ROUTE_BY_ACTION = {route.open_action_id: route.route_id for route in ROUTES}


def validate_full_product_actions() -> None:
    base_ids = {item.action_id for item in DEFAULT_ACTIONS}
    ids = [item.action_id for item in FULL_PRODUCT_ACTIONS]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate full-product action id")
    overlap = base_ids.intersection(ids)
    if overlap:
        raise ValueError(
            f"full-product action collides with Stage1 action: {sorted(overlap)!r}"
        )


def build_full_product_action_registry(
    *,
    bindings: Mapping[str, str | None] | None = None,
    aliases: Mapping[str, str | None] | None = None,
) -> ActionRegistry:
    """Return one registry containing inherited Stage1 and full-product actions."""
    validate_full_product_actions()
    return ActionRegistry(
        (*DEFAULT_ACTIONS, *FULL_PRODUCT_ACTIONS),
        bindings=bindings,
        aliases=aliases,
    )


@dataclass(frozen=True, slots=True)
class ActionDispatchResult:
    action_id: str
    handled_by_shell: bool
    route_id: str | None = None
    focus_target: str | None = None
    value: Any = None


class FullProductActionRouter:
    """Route shell actions locally and delegate every domain action unchanged."""

    def __init__(
        self,
        shell: AccessibleShellState,
        delegate: Callable[[str, Mapping[str, object]], Any],
        *,
        registry: ActionRegistry | None = None,
    ) -> None:
        if not callable(delegate):
            raise TypeError("full-product action delegate must be callable")
        self._shell = shell
        self._delegate = delegate
        self._registry = registry or build_full_product_action_registry()

    @property
    def registry(self) -> ActionRegistry:
        return self._registry

    def dispatch(
        self,
        action_id: str,
        payload: Mapping[str, object] | None = None,
        *,
        current_focus_id: str = "",
    ) -> ActionDispatchResult:
        self._registry.definition(action_id)
        self._shell._assert_action_dispatch_ready()
        route_id = _ROUTE_BY_ACTION.get(action_id)
        if route_id is not None:
            focus_target = self._shell.open_route(
                route_id,
                current_focus_id=current_focus_id,
            )
            return ActionDispatchResult(
                action_id=action_id,
                handled_by_shell=True,
                route_id=route_id,
                focus_target=focus_target,
            )
        if current_focus_id:
            self._shell.record_observed_focus(current_focus_id)
        value = self._delegate(action_id, dict(payload or {}))
        return ActionDispatchResult(
            action_id=action_id,
            handled_by_shell=False,
            value=value,
        )
