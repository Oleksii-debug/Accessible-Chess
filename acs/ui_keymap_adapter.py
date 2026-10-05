from __future__ import annotations

"""Presentation adapter for the central Accessible Chess action registry.

The UI may localize labels and project registry contexts to concrete WebView
interaction scopes, but action IDs, defaults and aliases come from
:mod:`acs.keybindings`. This keeps the Web UI from becoming a second source
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
    BindingContext.PGN_TREE: "pgn_tree",
    BindingContext.LIBRARY_RESULTS: "library_results",
    BindingContext.EDUCATION_LIST: "education_list",
    BindingContext.CLASSROOM_LIST: "classroom_list",
    BindingContext.TOOLBAR: "toolbar",
    BindingContext.PROFILE_DIALOG: "profile_dialog",
}

_UK_LABELS = {
    "screen.help": "Довідка",
    "history.previous": "Попередня позиція в історії",
    "history.next": "Наступна позиція в історії",
    "history.go_to_move": "Перейти до ходу",
    "history.commit_go_to_move": "Підтвердити перехід до введеного ходу",
    "file.new": "Нова стандартна позиція",
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
    "board.cursor_left": "Курсор дошки ліворуч",
    "board.cursor_right": "Курсор дошки праворуч",
    "board.cursor_up": "Курсор дошки вгору",
    "board.cursor_down": "Курсор дошки вниз",
    "board.activate": "Активувати поле дошки",
    "board.activate_alternative": "Активувати поле дошки, альтернативна клавіша",
    "board.exit": "Вийти з дошки",
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
    "move.submit": "Зробити введений хід",
    "move.undo": "Команда undo",
    "move.redo": "Команда redo",
    "move.last": "Команда останнього ходу",
    "move.white_to_move": "Команда ходу білих",
    "move.black_to_move": "Команда ходу чорних",
    "move.clear": "Команда очищення дошки",
    "move.standard": "Команда стандартної позиції",
    "move.empty": "Команда порожньої позиції",
    "pgn.previous_item": "Попередній елемент дерева PGN",
    "pgn.next_item": "Наступний елемент дерева PGN",
    "pgn.parent_variation": "Повернутися до батьківського варіанта",
    "library.previous_result": "Попередній результат бібліотеки",
    "library.next_result": "Наступний результат бібліотеки",
    "library.open_game": "Відкрити вибрану партію з бібліотеки",
    "education.previous_item": "Попередній навчальний елемент",
    "education.next_item": "Наступний навчальний елемент",
    "education.open_selected": "Відкрити вибраний навчальний елемент",
    "classroom.previous_item": "Попередній елемент класу",
    "classroom.next_item": "Наступний елемент класу",
    "classroom.first_item": "Перший елемент класу",
    "classroom.last_item": "Останній елемент класу",
    "classroom.open_selected": "Відкрити вибраний елемент класу",
    "toolbar.previous_control": "Попередній елемент панелі інструментів",
    "toolbar.next_control": "Наступний елемент панелі інструментів",
    "toolbar.first_control": "Перший елемент панелі інструментів",
    "toolbar.last_control": "Останній елемент панелі інструментів",
    "profile.save_name": "Зберегти ім’я локального профілю",
}

_EN_LABELS: dict[str, str] = {
    "screen.help": "Help",
    "history.commit_go_to_move": "Confirm typed history move",
    "move.submit": "Submit move",
    "board.cursor_left": "Move board cursor left",
    "board.cursor_right": "Move board cursor right",
    "board.cursor_up": "Move board cursor up",
    "board.cursor_down": "Move board cursor down",
    "board.activate": "Activate board square",
    "board.activate_alternative": "Activate board square, alternative key",
    "board.exit": "Exit board interaction",
    "classroom.previous_item": "Previous classroom item",
    "classroom.next_item": "Next classroom item",
    "classroom.first_item": "First classroom item",
    "classroom.last_item": "Last classroom item",
    "classroom.open_selected": "Open selected classroom item",
    "toolbar.previous_control": "Previous toolbar control",
    "toolbar.next_control": "Next toolbar control",
    "toolbar.first_control": "First toolbar control",
    "toolbar.last_control": "Last toolbar control",
    "profile.save_name": "Save local profile name",
}

for _number in range(1, 9):
    _file = "abcdefgh"[_number - 1]
    _UK_LABELS[f"board.rank_{_number}"] = f"Горизонталь {_number}"
    _UK_LABELS[f"board.file_{_number}"] = f"Вертикаль {_file}"
    _EN_LABELS[f"board.rank_{_number}"] = f"Rank {_number}"
    _EN_LABELS[f"board.file_{_number}"] = f"File {_file}"


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
                "labelEn": _EN_LABELS.get(definition.action_id, definition.title),
                "binding": registry.get_binding(definition.action_id),
                "alias": registry.get_alias(definition.action_id),
                "defaultBinding": definition.default_binding,
                "defaultAlias": definition.default_alias,
            }
        )
    return {"schemaVersion": SCHEMA_VERSION, "actions": actions}
