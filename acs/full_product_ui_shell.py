"""Accessible full-product navigation/focus model for the Windows WebView2 shell.

This module deliberately contains presentation state only.  It does not own chess
rules, GameTree, database, engine, import, or packaging behavior.  UI adapters
bind the stable route/action identifiers here to the central application command
registry owned by the product runtime.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Iterable, Mapping


class UILanguage(str, Enum):
    UA = "uk"
    EN = "en"


@dataclass(frozen=True, slots=True)
class ModuleRoute:
    route_id: str
    heading: Mapping[UILanguage, str]
    description: Mapping[UILanguage, str]
    landmark: str = "main"
    default_focus_id: str = ""
    open_action_id: str = ""

    def label(self, language: UILanguage) -> str:
        return self.heading[language]

    def help_text(self, language: UILanguage) -> str:
        return self.description[language]


ROUTES: tuple[ModuleRoute, ...] = (
    ModuleRoute("board", {UILanguage.UA: "Дошка і партія", UILanguage.EN: "Board and game"}, {UILanguage.UA: "Гра та навігація по шахівниці", UILanguage.EN: "Game and board navigation"}, default_focus_id="move-input", open_action_id="screen.board"),
    ModuleRoute("analysis", {UILanguage.UA: "Аналіз", UILanguage.EN: "Analysis"}, {UILanguage.UA: "Аналіз поточної позиції", UILanguage.EN: "Analyze the current position"}, default_focus_id="analysis-command", open_action_id="screen.analysis"),
    ModuleRoute("pgn", {UILanguage.UA: "PGN і дерево партії", UILanguage.EN: "PGN and game tree"}, {UILanguage.UA: "Партії, варіанти, коментарі та теги", UILanguage.EN: "Games, variations, comments, and tags"}, default_focus_id="pgn-game-list", open_action_id="screen.pgn"),
    ModuleRoute("library", {UILanguage.UA: "Бібліотека і пошук", UILanguage.EN: "Library and search"}, {UILanguage.UA: "Пошук і відкриття збережених партій", UILanguage.EN: "Search and open saved games"}, default_focus_id="library-search", open_action_id="screen.library"),
    ModuleRoute("books", {UILanguage.UA: "Книги", UILanguage.EN: "Books"}, {UILanguage.UA: "Структуроване читання шахових матеріалів", UILanguage.EN: "Structured chess material reading"}, default_focus_id="book-reader", open_action_id="screen.books"),
    ModuleRoute("training", {UILanguage.UA: "Тренування", UILanguage.EN: "Training"}, {UILanguage.UA: "Вправи, підказки та прогрес", UILanguage.EN: "Exercises, hints, and progress"}, default_focus_id="training-prompt", open_action_id="screen.training"),
    ModuleRoute("teacher", {UILanguage.UA: "Режим викладача", UILanguage.EN: "Teacher mode"}, {UILanguage.UA: "Візуальне пояснення для учня з керуванням із клавіатури", UILanguage.EN: "Keyboard-controlled visual teaching for a student"}, default_focus_id="teacher-pointer-input", open_action_id="screen.teacher"),
    ModuleRoute("classes", {UILanguage.UA: "Класи й учні", UILanguage.EN: "Classes and students"}, {UILanguage.UA: "Уроки, завдання та прогрес учнів", UILanguage.EN: "Lessons, assignments, and student progress"}, default_focus_id="classes-list", open_action_id="screen.classes"),
    ModuleRoute("settings", {UILanguage.UA: "Налаштування", UILanguage.EN: "Settings"}, {UILanguage.UA: "Параметри програми та доступності", UILanguage.EN: "Application and accessibility settings"}, default_focus_id="settings-list", open_action_id="screen.settings"),
    ModuleRoute("help", {UILanguage.UA: "Довідка", UILanguage.EN: "Help"}, {UILanguage.UA: "Команди клавіатури та короткі інструкції", UILanguage.EN: "Keyboard commands and concise instructions"}, default_focus_id="help-search", open_action_id="screen.help"),
)

_ROUTE_INDEX = {route.route_id: route for route in ROUTES}
_INTERNAL_ERROR_PATTERN = re.compile(
    r"(?:Traceback|File\s+\".*?\"|[A-Za-z]:\\|/[^\s]+\.py\b|sqlite|UCI\s+error|HRESULT)",
    re.IGNORECASE,
)


class AccessibleShellState:
    """Deterministic presentation-only route and focus state.

    Focus is restored per route.  The shell never invents module hotkeys; callers
    dispatch ``open_action_id`` through the central application action registry.
    """

    def __init__(self, *, language: UILanguage = UILanguage.UA, initial_route: str = "board") -> None:
        if initial_route not in _ROUTE_INDEX:
            raise ValueError("unknown UI route")
        self._language = language
        self._route_id = initial_route
        self._focus_by_route: dict[str, str] = {}

    @property
    def language(self) -> UILanguage:
        return self._language

    @property
    def current_route(self) -> ModuleRoute:
        return _ROUTE_INDEX[self._route_id]

    def set_language(self, language: UILanguage) -> None:
        self._language = language

    def record_focus(self, element_id: str) -> None:
        clean = element_id.strip()
        if clean:
            self._focus_by_route[self._route_id] = clean

    def open_route(self, route_id: str, *, current_focus_id: str = "") -> str:
        if route_id not in _ROUTE_INDEX:
            raise ValueError("unknown UI route")
        if current_focus_id.strip():
            self.record_focus(current_focus_id)
        self._route_id = route_id
        return self.restore_focus_target()

    def restore_focus_target(self) -> str:
        route = self.current_route
        return self._focus_by_route.get(route.route_id, route.default_focus_id)

    def navigation_items(self) -> tuple[dict[str, str], ...]:
        return tuple(
            {
                "route_id": route.route_id,
                "label": route.label(self._language),
                "description": route.help_text(self._language),
                "action_id": route.open_action_id,
                "landmark": route.landmark,
            }
            for route in ROUTES
        )


def is_standard_editing_shortcut(key: str, modifiers: Iterable[str]) -> bool:
    """Return True for editing shortcuts that global app keymaps must not steal."""
    normalized = key.strip().lower()
    mods = {item.strip().lower() for item in modifiers}
    return "ctrl" in mods and normalized in {"a", "c", "x", "v", "z", "y"}


def should_global_keymap_handle(*, key: str, modifiers: Iterable[str], editable: bool) -> bool:
    if editable and is_standard_editing_shortcut(key, modifiers):
        return False
    return True


def concise_user_error(message: object, *, language: UILanguage = UILanguage.UA) -> str:
    """Project failures into concise user speech without developer internals."""
    text = str(message or "").strip()
    if not text:
        return "Не вдалося виконати дію." if language is UILanguage.UA else "The action could not be completed."
    if _INTERNAL_ERROR_PATTERN.search(text) or len(text) > 180:
        return "Не вдалося виконати дію." if language is UILanguage.UA else "The action could not be completed."
    return text


def validate_routes(routes: Iterable[ModuleRoute] = ROUTES) -> None:
    seen_routes: set[str] = set()
    seen_actions: set[str] = set()
    for route in routes:
        if not route.route_id or route.route_id in seen_routes:
            raise ValueError("duplicate or empty route id")
        if not route.open_action_id or route.open_action_id in seen_actions:
            raise ValueError("duplicate or empty action id")
        if not route.default_focus_id:
            raise ValueError("every route requires a keyboard focus target")
        for language in UILanguage:
            if not route.heading.get(language, "").strip():
                raise ValueError("missing localized heading")
            if not route.description.get(language, "").strip():
                raise ValueError("missing localized description")
        seen_routes.add(route.route_id)
        seen_actions.add(route.open_action_id)
