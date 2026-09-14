from __future__ import annotations

"""Full-product V2 composition profile for current Windows integration work.

This profile extends the accepted Version 2 checkpoint with the dependency-complete
Teacher/Classes navigation seams and the bounded Education read/open actions whose
trusted-host handlers are composed by the current Education application. It
deliberately does not expose ``remote.*`` or uncomposed Teacher/Classroom mutation
actions.
"""

from collections.abc import Callable, Mapping
from typing import Any

from .full_product_actions import FULL_PRODUCT_ACTIONS, FullProductActionRouter
from .full_product_native_menu import (
    FullProductNativeMenuController,
    NativeMenuItemKind,
    NativeMenuItemSpec,
    NativeTopMenuSpec,
)
from .full_product_ui_shell import AccessibleShellState, UILanguage
from .full_product_webview_adapter import FullProductWebViewAdapter
from .keybindings import ActionRegistry, DEFAULT_ACTIONS
from .version2_profile import (
    VERSION2_FULL_PRODUCT_ACTIONS,
    build_version2_action_registry,
    build_version2_menu_spec,
)

FINAL_PRODUCT_EXTRA_SCREEN_ACTION_IDS = frozenset(
    {"screen.teacher", "screen.classes"}
)
FINAL_PRODUCT_SAFE_EDUCATION_READ_ACTION_IDS = frozenset(
    {
        "classes.open",
        "classes.student_open",
        "classes.lesson_open",
        "classes.assignment_open",
    }
)
FINAL_PRODUCT_EXTRA_ACTION_IDS = (
    FINAL_PRODUCT_EXTRA_SCREEN_ACTION_IDS | FINAL_PRODUCT_SAFE_EDUCATION_READ_ACTION_IDS
)
FINAL_PRODUCT_EXTRA_ACTIONS = tuple(
    definition
    for definition in FULL_PRODUCT_ACTIONS
    if definition.action_id in FINAL_PRODUCT_EXTRA_ACTION_IDS
)
if frozenset(definition.action_id for definition in FINAL_PRODUCT_EXTRA_ACTIONS) != FINAL_PRODUCT_EXTRA_ACTION_IDS:
    raise RuntimeError("full-product extra action definitions are incomplete")

FINAL_PRODUCT_ACTIONS = (*VERSION2_FULL_PRODUCT_ACTIONS, *FINAL_PRODUCT_EXTRA_ACTIONS)
FINAL_PRODUCT_ACTION_IDS = frozenset(
    definition.action_id for definition in FINAL_PRODUCT_ACTIONS
)


def build_final_product_action_registry(
    *,
    bindings: Mapping[str, str | None] | None = None,
    aliases: Mapping[str, str | None] | None = None,
) -> ActionRegistry:
    registry = ActionRegistry(
        (*DEFAULT_ACTIONS, *FINAL_PRODUCT_ACTIONS),
        bindings=bindings,
        aliases=aliases,
    )
    validate_final_product_action_registry(registry)
    return registry


def validate_final_product_action_registry(registry: ActionRegistry) -> None:
    if not isinstance(registry, ActionRegistry):
        raise TypeError("full-product registry must be ActionRegistry")
    ids = frozenset(definition.action_id for definition in registry.definitions())
    required = frozenset(definition.action_id for definition in DEFAULT_ACTIONS).union(
        FINAL_PRODUCT_ACTION_IDS
    )
    if ids != required:
        raise ValueError("full-product registry contains unexpected or missing actions")
    if any(action_id.startswith("remote.") for action_id in ids):
        raise ValueError("remote transport actions require an approved Product contract")
    forbidden = {
        "teacher.pointer_input",
        "teacher.pointer_clear",
        "teacher.coordinates_toggle",
        "teacher.orientation_toggle",
        "teacher.read_student_event",
        "student.move",
        "classes.new",
    }
    leaked = ids.intersection(forbidden)
    if leaked:
        raise ValueError("uncomposed Teacher/Classroom mutation actions are exposed")


def build_final_product_shell(
    *,
    language: UILanguage = UILanguage.UA,
    initial_route: str = "board",
) -> AccessibleShellState:
    return AccessibleShellState(language=language, initial_route=initial_route)


def build_final_product_router(
    shell: AccessibleShellState,
    delegate: Callable[[str, Mapping[str, object]], Any],
    *,
    registry: ActionRegistry | None = None,
) -> FullProductActionRouter:
    if not isinstance(shell, AccessibleShellState):
        raise TypeError("full-product router requires AccessibleShellState")
    selected = registry or build_final_product_action_registry()
    validate_final_product_action_registry(selected)
    return FullProductActionRouter(shell, delegate, registry=selected)


def build_final_product_webview_adapter(
    shell: AccessibleShellState,
    router: FullProductActionRouter,
) -> FullProductWebViewAdapter:
    return FullProductWebViewAdapter(shell, router)


_MENU_TEXT = {
    UILanguage.UA: {
        "top": "&Учитель/Клас",
        "teacher": "Режим викладача",
        "classes": "Класи та учні",
    },
    UILanguage.EN: {
        "top": "&Teacher/Classroom",
        "teacher": "Teacher mode",
        "classes": "Classes and students",
    },
}


def _language(value: UILanguage | str) -> UILanguage:
    if isinstance(value, UILanguage):
        return value
    if type(value) is not str:
        raise TypeError("native menu language must be text or UILanguage")
    try:
        return UILanguage(value.strip().lower())
    except ValueError as exc:
        raise ValueError("unsupported native menu language") from exc


def build_final_product_menu_spec(
    registry: ActionRegistry,
    *,
    language: UILanguage | str,
) -> tuple[NativeTopMenuSpec, ...]:
    """Keep the accepted V2 menu and add only safe Teacher/Classes navigation."""

    validate_final_product_action_registry(registry)
    profile = registry.to_profile()
    bindings = profile.get("bindings")
    aliases = profile.get("aliases")
    if not isinstance(bindings, Mapping) or not isinstance(aliases, Mapping):
        raise ValueError("full-product keymap profile is invalid")

    # The accepted V2 menus are rebuilt against their exact narrower registry so
    # their validator remains useful instead of being bypassed.
    base_ids = frozenset(
        definition.action_id for definition in (*DEFAULT_ACTIONS, *VERSION2_FULL_PRODUCT_ACTIONS)
    )
    base_registry = build_version2_action_registry(
        bindings={key: value for key, value in bindings.items() if key in base_ids},
        aliases={key: value for key, value in aliases.items() if key in base_ids},
    )
    base = list(build_version2_menu_spec(base_registry, language=language))
    lang = _language(language)
    text = _MENU_TEXT[lang]

    def action(label: str, action_id: str) -> NativeMenuItemSpec:
        registry.definition(action_id)
        binding = registry.get_binding(action_id)
        if binding:
            label = f"{label}\t{binding}"
        return NativeMenuItemSpec(
            NativeMenuItemKind.ACTION,
            label,
            action_id=action_id,
        )

    teacher = NativeTopMenuSpec(
        "teacher",
        text["top"],
        (
            action(text["teacher"], "screen.teacher"),
            action(text["classes"], "screen.classes"),
        ),
    )
    insert_at = next(
        (index for index, menu in enumerate(base) if menu.menu_id == "settings"),
        len(base),
    )
    base.insert(insert_at, teacher)
    return tuple(base)


class FinalProductNativeMenuController(FullProductNativeMenuController):
    def spec(self) -> tuple[NativeTopMenuSpec, ...]:
        return build_final_product_menu_spec(
            self._adapter.registry,
            language=self._adapter.shell.language,
        )


def validate_final_product_profile() -> None:
    registry = build_final_product_action_registry()
    shell = build_final_product_shell()
    router = build_final_product_router(shell, lambda action_id, payload: None, registry=registry)
    adapter = build_final_product_webview_adapter(shell, router)
    navigation = tuple(item["route_id"] for item in adapter.snapshot()["navigation"])
    for required in ("teacher", "classes"):
        if required not in navigation:
            raise ValueError(f"full-product navigation is missing {required}")
    build_final_product_menu_spec(registry, language=shell.language)


validate_final_product_profile()
