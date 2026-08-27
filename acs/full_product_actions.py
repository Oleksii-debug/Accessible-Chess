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
        )
        for route in ROUTES
    ),
    _action("pgn.open", BindingContext.DOCUMENT, "Open PGN"),
    _action("pgn.select_item", BindingContext.DOCUMENT, "Select GameTree item"),
    _action("pgn.previous_game", BindingContext.DOCUMENT, "Previous PGN game"),
    _action("pgn.next_game", BindingContext.DOCUMENT, "Next PGN game"),
    _action("pgn.previous_item", BindingContext.DOCUMENT, "Previous GameTree item"),
    _action("pgn.next_item", BindingContext.DOCUMENT, "Next GameTree item"),
    _action("pgn.parent_variation", BindingContext.DOCUMENT, "Return to parent variation"),
    _action("pgn.comment_edit", BindingContext.DOCUMENT, "Add or edit GameTree comment"),
    _action("pgn.comment_delete", BindingContext.DOCUMENT, "Delete GameTree comment"),
    _action("pgn.variation_delete", BindingContext.DOCUMENT, "Delete variation"),
    _action("pgn.variation_promote", BindingContext.DOCUMENT, "Promote variation"),
    _action("pgn.copy_selection", BindingContext.DOCUMENT, "Copy selected game or variation"),
    _action("pgn.export_selection", BindingContext.DOCUMENT, "Export selected game or variation"),
    _action("library.search", BindingContext.DATABASE, "Search library"),
    _action("library.reset_filters", BindingContext.DATABASE, "Reset library filters"),
    _action("library.next_page", BindingContext.DATABASE, "Next library page"),
    _action("library.previous_page", BindingContext.DATABASE, "Previous library page"),
    _action("library.open_game", BindingContext.DATABASE, "Open selected library game"),
    _action("library.import", BindingContext.DATABASE, "Import into library"),
    _action("library.cancel_import", BindingContext.DATABASE, "Cancel library import"),
    _action("library.export", BindingContext.DATABASE, "Export from library"),
    _action("book.previous_block", BindingContext.BOOK_READER, "Previous book block"),
    _action("book.next_block", BindingContext.BOOK_READER, "Next book block"),
    _action("book.previous_heading", BindingContext.BOOK_READER, "Previous book heading"),
    _action("book.next_heading", BindingContext.BOOK_READER, "Next book heading"),
    _action("book.next_position", BindingContext.BOOK_READER, "Next book position"),
    _action("book.next_game", BindingContext.BOOK_READER, "Next book game"),
    _action("book.bookmark", BindingContext.BOOK_READER, "Save book return point"),
    _action("book.open_position", BindingContext.BOOK_READER, "Open book position on board"),
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
    _action("student.move", BindingContext.DOCUMENT, "Submit explicit student move"),
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
        value = self._delegate(action_id, dict(payload or {}))
        return ActionDispatchResult(
            action_id=action_id,
            handled_by_shell=False,
            value=value,
        )
