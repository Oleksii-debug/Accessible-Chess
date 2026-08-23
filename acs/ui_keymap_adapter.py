from __future__ import annotations

"""Presentation adapter for the central Accessible Chess action registry.

The UI may localize labels and project registry contexts to concrete WebView
interaction scopes, but action IDs, defaults and aliases come from
:mod:`acs.keybindings`.  This keeps the Web UI from becoming a second source
of truth for keyboard behavior.
"""

from typing import Any

from .keybindings import ActionRegistry, BindingContext, SCHEMA_VERSION


_UI_CONTEXT = {
    BindingContext.GLOBAL: "document",
    BindingContext.DOCUMENT: "document",
    BindingContext.HISTORY: "document",
    BindingContext.ANALYSIS: "analysis",
    BindingContext.BOARD: "board",
    BindingContext.MOVE_ENTRY: "move-entry",
    BindingContext.POSITION_EDITOR: "position-editor",
    BindingContext.ENGINE_GAME: "engine-game",
    BindingContext.DATABASE: "database",
    BindingContext.BOOK_READER: "book-reader",
}

_UK_LABELS = {
    "history.previous": "Попередня позиція в історії",
    "history.next": "Наступна позиція в історії",
    "history.go_to_move": "Перейти до ходу",
    "edit.undo": "Скасувати хід",
    "edit.redo": "Повторити хід",
    "analysis.pv1": "Перший варіант Stockfish",
    "analysis.pv2": "Другий варіант Stockfish",
    "analysis.pv3": "Третій варіант Stockfish",
    "analysis.pv4": "Четвертий варіант Stockfish",
    "analysis.pv5": "П’ятий варіант Stockfish",
    "analysis.previous_pv": "Попередній варіант Stockfish",
    "analysis.next_pv": "Наступний варіант Stockfish",
    "analysis.lock_target": "Зафіксувати ціль аналізу або стежити за позицією",
    "analysis.explore_pv": "Тимчасово переглянути вибраний варіант",
    "analysis.return": "Повернутися з тимчасового варіанта",
    "analysis.insert_move": "Вставити вибраний хід Stockfish",
    "analysis.insert_line": "Вставити вибраний варіант Stockfish",
    "analysis.restart": "Перезапустити аналіз Stockfish",
    "board.current": "Поточне поле",
    "board.last_captured": "Остання взята фігура",
    "board.last_move": "Останній хід",
    "board.my_clock": "Мій час",
    "board.opponent_clock": "Час суперника",
    "board.legal_moves": "Легальні ходи",
    "board.captures": "Взяття",
    "board.surroundings": "Оточення поля",
    "board.attackers": "Атакуючі",
    "board.defenders": "Захисники",
    "board.material": "Матеріальний баланс",
    "board.evaluation": "Оцінка позиції",
    "board.best_move": "Найкращий хід",
    "board.play_best": "Зіграти найкращий хід",
    "board.next_king": "Наступний король",
    "board.next_queen": "Наступний ферзь",
    "board.next_rook": "Наступна тура",
    "board.next_bishop": "Наступний слон",
    "board.next_knight": "Наступний кінь",
    "board.next_pawn": "Наступний пішак",
    "board.previous_king": "Попередній король",
    "board.previous_queen": "Попередній ферзь",
    "board.previous_rook": "Попередня тура",
    "board.previous_bishop": "Попередній слон",
    "board.previous_knight": "Попередній кінь",
    "board.previous_pawn": "Попередній пішак",
    "board.input": "Поле введення ходу",
    "move.undo": "Команда undo",
    "move.redo": "Команда redo",
    "move.last": "Команда останнього ходу",
    "move.white_to_move": "Команда ходу білих",
    "move.black_to_move": "Команда ходу чорних",
    "move.clear": "Команда очищення дошки",
    "move.standard": "Команда стандартної позиції",
    "move.empty": "Команда порожньої позиції",
}

for _number in range(1, 9):
    _UK_LABELS[f"board.rank_{_number}"] = f"Горизонталь {_number}"
    _UK_LABELS[f"board.file_{_number}"] = f"Вертикаль {'abcdefgh'[_number - 1]}"


def build_web_keymap(registry: ActionRegistry | None = None) -> dict[str, Any]:
    registry = registry or ActionRegistry()
    actions: list[dict[str, Any]] = []
    for definition in registry.definitions():
        if definition.external:
            continue
        actions.append(
            {
                "id": definition.action_id,
                "context": _UI_CONTEXT[definition.context],
                "registryContext": definition.context.value,
                "labelUk": _UK_LABELS.get(definition.action_id, definition.title),
                "labelEn": definition.title,
                "binding": registry.get_binding(definition.action_id),
                "alias": registry.get_alias(definition.action_id),
                "defaultBinding": definition.default_binding,
                "defaultAlias": definition.default_alias,
            }
        )
    return {"schemaVersion": SCHEMA_VERSION, "actions": actions}
