from __future__ import annotations

"""Version 2 Windows/NVDA composition profile.

Version 2 is intentionally narrower than the repository's full long-term product
preview. This module composes the already-owned shell, ActionRegistry, WebView
adapter and native-menu implementation while exposing only the Version 2 release
surface: Board/Analysis, PGN/GameTree, Library/Search, Books, Settings and Help.

Teacher/Classroom, Training, Classes/Education and Remote remain preserved in the
repository but are not made visible by this profile. No chess, PGN, database or
book rules are implemented here.
"""

from collections.abc import Callable, Mapping
from typing import Any

from .full_product_actions import (
    FULL_PRODUCT_ACTIONS,
    FullProductActionRouter,
    build_full_product_action_registry,
)
from .full_product_native_menu import (
    FullProductNativeMenuController,
    NativeMenuItemKind,
    NativeTopMenuSpec,
    build_full_product_menu_spec,
)
from .full_product_ui_shell import (
    ROUTES,
    AccessibleShellState,
    ModuleRoute,
    UILanguage,
)
from .full_product_webview_adapter import FullProductWebViewAdapter
from .keybindings import ActionRegistry, DEFAULT_ACTIONS


VERSION2_ROUTE_IDS: tuple[str, ...] = (
    "board",
    "analysis",
    "pgn",
    "library",
    "books",
    "settings",
    "help",
)

VERSION2_TOP_MENU_IDS: tuple[str, ...] = (
    "file",
    "game",
    "position",
    "pgn",
    "library",
    "import",
    "export",
    "engine",
    "analysis",
    "books",
    "settings",
    "help",
)

_VERSION2_ROUTE_ID_SET = frozenset(VERSION2_ROUTE_IDS)
_VERSION2_ROUTE_INDEX: dict[str, ModuleRoute] = {
    route.route_id: route for route in ROUTES if route.route_id in _VERSION2_ROUTE_ID_SET
}
VERSION2_ROUTES: tuple[ModuleRoute, ...] = tuple(
    _VERSION2_ROUTE_INDEX[route_id] for route_id in VERSION2_ROUTE_IDS
)

_VERSION2_DOMAIN_PREFIXES = ("pgn.", "library.", "book.")
_VERSION2_SCREEN_ACTION_IDS = frozenset(route.open_action_id for route in VERSION2_ROUTES)
VERSION2_FULL_PRODUCT_ACTIONS = tuple(
    definition
    for definition in FULL_PRODUCT_ACTIONS
    if definition.action_id in _VERSION2_SCREEN_ACTION_IDS
    or definition.action_id.startswith(_VERSION2_DOMAIN_PREFIXES)
)
VERSION2_FULL_PRODUCT_ACTION_IDS = frozenset(
    definition.action_id for definition in VERSION2_FULL_PRODUCT_ACTIONS
)

_VERSION2_FORBIDDEN_ACTIONS = frozenset(
    {
        "screen.training",
        "screen.teacher",
        "screen.classes",
        "training.submit",
        "teacher.pointer_input",
        "student.move",
        "classes.open",
        "remote.connect",
    }
)


def build_version2_action_registry(
    *,
    bindings: Mapping[str, str | None] | None = None,
    aliases: Mapping[str, str | None] | None = None,
) -> ActionRegistry:
    """Build the one ActionRegistry used by the Version 2 release profile."""

    registry = ActionRegistry(
        (*DEFAULT_ACTIONS, *VERSION2_FULL_PRODUCT_ACTIONS),
        bindings=bindings,
        aliases=aliases,
    )
    validate_version2_action_registry(registry)
    return registry


def validate_version2_action_registry(registry: ActionRegistry) -> None:
    if not isinstance(registry, ActionRegistry):
        raise TypeError("Version 2 registry must be ActionRegistry")
    ids = frozenset(definition.action_id for definition in registry.definitions())
    required = frozenset(definition.action_id for definition in DEFAULT_ACTIONS).union(
        VERSION2_FULL_PRODUCT_ACTION_IDS
    )
    if ids != required:
        raise ValueError("Version 2 registry contains unexpected or missing actions")
    forbidden = ids.intersection(_VERSION2_FORBIDDEN_ACTIONS)
    if forbidden:
        raise ValueError("Version 2 registry exposes deferred product actions")


class Version2ShellState(AccessibleShellState):
    """Full-product shell semantics restricted to dependency-complete V2 routes."""

    def __init__(
        self,
        *,
        language: UILanguage = UILanguage.UA,
        initial_route: str = "board",
    ) -> None:
        if initial_route not in _VERSION2_ROUTE_INDEX:
            raise ValueError("unknown Version 2 UI route")
        super().__init__(language=language, initial_route="board")
        self._route_id = initial_route

    @property
    def current_route(self) -> ModuleRoute:
        return _VERSION2_ROUTE_INDEX[self._route_id]

    def open_route(self, route_id: str, *, current_focus_id: str = "") -> str:
        if route_id not in _VERSION2_ROUTE_INDEX:
            raise ValueError("unknown Version 2 UI route")
        if self._dialogs:
            raise RuntimeError("close active dialog before changing application route")
        if self._clean_focus_id(current_focus_id):
            self.record_focus(current_focus_id)
        self._route_id = route_id
        return self.restore_focus_target()

    def navigation_items(self) -> tuple[dict[str, str], ...]:
        return tuple(
            {
                "route_id": route.route_id,
                "label": route.label(self._language),
                "description": route.help_text(self._language),
                "action_id": route.open_action_id,
                "landmark": route.landmark,
                "current": "true" if route.route_id == self._route_id else "false",
            }
            for route in VERSION2_ROUTES
        )


def build_version2_shell(
    *,
    language: UILanguage = UILanguage.UA,
    initial_route: str = "board",
) -> Version2ShellState:
    return Version2ShellState(language=language, initial_route=initial_route)


def build_version2_router(
    shell: Version2ShellState,
    delegate: Callable[[str, Mapping[str, object]], Any],
    *,
    registry: ActionRegistry | None = None,
) -> FullProductActionRouter:
    if not isinstance(shell, Version2ShellState):
        raise TypeError("Version 2 router requires Version2ShellState")
    selected_registry = registry or build_version2_action_registry()
    validate_version2_action_registry(selected_registry)
    return FullProductActionRouter(shell, delegate, registry=selected_registry)


def build_version2_webview_adapter(
    shell: Version2ShellState,
    router: FullProductActionRouter,
) -> FullProductWebViewAdapter:
    return FullProductWebViewAdapter(shell, router)


def build_version2_menu_spec(
    registry: ActionRegistry,
    *,
    language: UILanguage | str,
) -> tuple[NativeTopMenuSpec, ...]:
    """Reuse the owner native-menu definition then filter to the V2 profile."""

    validate_version2_action_registry(registry)
    profile = registry.to_profile()
    bindings = profile.get("bindings")
    aliases = profile.get("aliases")
    if not isinstance(bindings, Mapping) or not isinstance(aliases, Mapping):
        raise ValueError("Version 2 keymap profile is invalid")

    superset = build_full_product_action_registry(bindings=bindings, aliases=aliases)
    full_spec = build_full_product_menu_spec(superset, language=language)
    wanted = frozenset(VERSION2_TOP_MENU_IDS)
    selected = tuple(menu for menu in full_spec if menu.menu_id in wanted)
    if tuple(menu.menu_id for menu in selected) != VERSION2_TOP_MENU_IDS:
        raise ValueError("Version 2 native menu profile is incomplete")

    for menu in selected:
        for item in menu.items:
            if item.kind is NativeMenuItemKind.ACTION:
                registry.definition(item.action_id)
    return selected


class Version2NativeMenuController(FullProductNativeMenuController):
    """Owner controller behavior with only the Version 2 menu projection changed."""

    def spec(self) -> tuple[NativeTopMenuSpec, ...]:
        return build_version2_menu_spec(
            self._adapter.registry,
            language=self._adapter.shell.language,
        )


def validate_version2_profile() -> None:
    if tuple(route.route_id for route in VERSION2_ROUTES) != VERSION2_ROUTE_IDS:
        raise ValueError("Version 2 route profile is incomplete")
    registry = build_version2_action_registry()
    shell = build_version2_shell()
    router = build_version2_router(shell, lambda action_id, payload: None, registry=registry)
    adapter = build_version2_webview_adapter(shell, router)
    snapshot = adapter.snapshot()
    route_ids = tuple(item["route_id"] for item in snapshot["navigation"])
    if route_ids != VERSION2_ROUTE_IDS:
        raise ValueError("Version 2 WebView navigation does not match the profile")
    build_version2_menu_spec(registry, language=shell.language)


validate_version2_profile()
