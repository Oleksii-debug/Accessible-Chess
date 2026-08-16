from __future__ import annotations

from typing import Mapping

from .keybindings import ActionDefinition, ActionRegistry, BindingContext, DEFAULT_ACTIONS


# Teaching actions extend the existing central ActionRegistry. They deliberately
# have no hard-coded default shortcuts in this foundation slice: the same
# registry/remapping machinery used by the release UI owns any eventual binding.
TEACHING_ACTIONS: tuple[ActionDefinition, ...] = (
    ActionDefinition("teaching.pointer_input", BindingContext.DOCUMENT, "Coach pointer input"),
    ActionDefinition("teaching.annotation.square", BindingContext.DOCUMENT, "Add square annotation"),
    ActionDefinition("teaching.annotation.arrow", BindingContext.DOCUMENT, "Add arrow annotation"),
    ActionDefinition("teaching.lesson.previous_position", BindingContext.DOCUMENT, "Previous prepared position"),
    ActionDefinition("teaching.lesson.next_position", BindingContext.DOCUMENT, "Next prepared position"),
    ActionDefinition("teaching.lesson.deploy_position", BindingContext.DOCUMENT, "Deploy prepared position"),
    ActionDefinition("teaching.lesson.target_all", BindingContext.DOCUMENT, "Target all students"),
    ActionDefinition("teaching.lesson.target_group", BindingContext.DOCUMENT, "Target a student group"),
    ActionDefinition("teaching.lesson.target_selected", BindingContext.DOCUMENT, "Target selected students"),
    ActionDefinition("teaching.rotation.previous_board", BindingContext.DOCUMENT, "Previous supervised board"),
    ActionDefinition("teaching.rotation.next_board", BindingContext.DOCUMENT, "Next supervised board"),
    ActionDefinition("teaching.rotation.next_round", BindingContext.DOCUMENT, "Create next rotation round"),
    ActionDefinition("teaching.rotation.return_demo", BindingContext.DOCUMENT, "Return to demonstration mode"),
)


def build_teaching_action_registry(
    *,
    bindings: Mapping[str, str | None] | None = None,
    aliases: Mapping[str, str | None] | None = None,
) -> ActionRegistry:
    """Compose teaching commands into the application's existing ActionRegistry."""

    return ActionRegistry(
        (*DEFAULT_ACTIONS, *TEACHING_ACTIONS),
        bindings=bindings,
        aliases=aliases,
    )
