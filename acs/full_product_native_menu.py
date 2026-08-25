from __future__ import annotations

"""Windows-native menu projection for the isolated Full Product preview.

Stage 1 keeps its frozen six-menu release surface.  This module builds the
larger Full Product menu from the same :class:`ActionRegistry` used by WebView
navigation and routes every action back through :class:`FullProductWebViewAdapter`.
It therefore adds no second command or chess authority.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .full_product_ui_shell import UILanguage
from .full_product_webview_adapter import FullProductWebViewAdapter, WebViewCommand
from .keybindings import ActionRegistry
from .ui_native_menu import _resolve_windows_host_form, _same_managed_object


class NativeMenuItemKind(str, Enum):
    ACTION = "action"
    SEPARATOR = "separator"
    HOST = "host"


@dataclass(frozen=True, slots=True)
class NativeMenuItemSpec:
    kind: NativeMenuItemKind
    label: str = ""
    action_id: str = ""
    host_command: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.kind, NativeMenuItemKind):
            raise TypeError("native menu item kind is invalid")
        if not all(isinstance(value, str) for value in (self.label, self.action_id, self.host_command)):
            raise TypeError("native menu item fields must be text")
        if self.kind is NativeMenuItemKind.SEPARATOR:
            if self.label or self.action_id or self.host_command:
                raise ValueError("native menu separator must not carry commands")
            return
        if not self.label.strip():
            raise ValueError("native menu item label must not be empty")
        if self.kind is NativeMenuItemKind.ACTION:
            if not self.action_id or self.host_command:
                raise ValueError("native action item requires exactly one action id")
        elif self.kind is NativeMenuItemKind.HOST:
            if self.action_id or self.host_command != "app.exit":
                raise ValueError("unsupported native host command")


@dataclass(frozen=True, slots=True)
class NativeTopMenuSpec:
    menu_id: str
    label: str
    items: tuple[NativeMenuItemSpec, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.menu_id, str) or not self.menu_id.strip():
            raise ValueError("native top menu id must not be empty")
        if not isinstance(self.label, str) or not self.label.strip():
            raise ValueError("native top menu label must not be empty")
        if not isinstance(self.items, tuple) or not self.items:
            raise ValueError("native top menu requires items")
        if any(not isinstance(item, NativeMenuItemSpec) for item in self.items):
            raise TypeError("native top menu items are invalid")


_TOP_ORDER = (
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
    "training",
    "teacher",
    "settings",
    "help",
)

_TEXT = {
    UILanguage.EN: {
        "top.file": "&File", "top.game": "&Game", "top.position": "&Position",
        "top.pgn": "&PGN", "top.library": "&Library", "top.import": "&Import",
        "top.export": "&Export", "top.engine": "&Engine", "top.analysis": "&Analysis",
        "top.books": "&Books", "top.training": "&Training",
        "top.teacher": "&Teacher/Classroom", "top.settings": "&Settings", "top.help": "&Help",
        "open_pgn": "Open PGN", "import_library": "Import into Library",
        "export_pgn": "Export selected PGN", "exit": "Exit",
        "board_game": "Board and game", "standard": "New standard position",
        "empty": "Empty position", "undo": "Undo", "redo": "Redo",
        "position_tools": "Board and position tools", "move_input": "Move input",
        "history_go": "Go to move", "history_previous": "Previous history position",
        "history_next": "Next history position", "pgn_screen": "PGN and GameTree",
        "previous_game": "Previous game", "next_game": "Next game",
        "copy_pgn": "Copy selected game or variation", "library_screen": "Library and search",
        "library_search": "Search", "library_reset": "Reset filters",
        "library_open": "Open selected game", "library_export": "Export from Library",
        "analysis_screen": "Engine analysis", "analysis_restart": "Restart analysis",
        "analysis_lock": "Lock or follow target", "analysis_return": "Return to source",
        "previous_pv": "Previous variation", "next_pv": "Next variation",
        "explore_pv": "Temporarily explore variation", "insert_move": "Insert selected move",
        "insert_line": "Insert selected variation", "books_screen": "Book Library",
        "book_previous_heading": "Previous heading", "book_next_heading": "Next heading",
        "book_next_position": "Next position", "book_next_game": "Next book game",
        "book_bookmark": "Save bookmark", "book_open_position": "Open position on board",
        "book_return": "Return to book", "training_screen": "Training",
        "training_hint": "Hint", "training_reveal": "Reveal solution",
        "training_retry": "Try again", "training_reset": "Restart exercise",
        "teacher_screen": "Teacher board", "teacher_pointer_clear": "Clear teacher pointer",
        "teacher_coordinates": "Toggle coordinates", "teacher_orientation": "Toggle orientation",
        "teacher_event": "Read latest student event", "classes_screen": "Classes and students",
        "settings_screen": "Settings", "help_screen": "Keyboard and help",
    },
    UILanguage.UA: {
        "top.file": "&Файл", "top.game": "&Гра", "top.position": "&Позиція",
        "top.pgn": "&PGN", "top.library": "&Бібліотека", "top.import": "&Імпорт",
        "top.export": "&Експорт", "top.engine": "&Stockfish", "top.analysis": "&Аналіз",
        "top.books": "&Книги", "top.training": "&Тренування",
        "top.teacher": "&Учитель/Клас", "top.settings": "&Налаштування", "top.help": "&Довідка",
        "open_pgn": "Відкрити PGN", "import_library": "Імпортувати до бібліотеки",
        "export_pgn": "Експортувати вибране PGN", "exit": "Вихід",
        "board_game": "Дошка і партія", "standard": "Нова стандартна позиція",
        "empty": "Порожня позиція", "undo": "Скасувати", "redo": "Повторити",
        "position_tools": "Дошка та інструменти позиції", "move_input": "Поле введення ходу",
        "history_go": "Перейти до ходу", "history_previous": "Попередня позиція історії",
        "history_next": "Наступна позиція історії", "pgn_screen": "PGN і дерево партії",
        "previous_game": "Попередня партія", "next_game": "Наступна партія",
        "copy_pgn": "Копіювати вибрану партію або варіант", "library_screen": "Бібліотека і пошук",
        "library_search": "Пошук", "library_reset": "Скинути фільтри",
        "library_open": "Відкрити вибрану партію", "library_export": "Експортувати з бібліотеки",
        "analysis_screen": "Аналіз Stockfish", "analysis_restart": "Перезапустити аналіз",
        "analysis_lock": "Зафіксувати ціль або стежити", "analysis_return": "Повернутися до джерела",
        "previous_pv": "Попередній варіант", "next_pv": "Наступний варіант",
        "explore_pv": "Тимчасово переглянути варіант", "insert_move": "Вставити вибраний хід",
        "insert_line": "Вставити вибраний варіант", "books_screen": "Бібліотека книг",
        "book_previous_heading": "Попередній заголовок", "book_next_heading": "Наступний заголовок",
        "book_next_position": "Наступна позиція", "book_next_game": "Наступна партія в книзі",
        "book_bookmark": "Зберегти закладку", "book_open_position": "Відкрити позицію на дошці",
        "book_return": "Повернутися до книги", "training_screen": "Тренування",
        "training_hint": "Підказка", "training_reveal": "Показати розв’язок",
        "training_retry": "Спробувати ще раз", "training_reset": "Почати вправу спочатку",
        "teacher_screen": "Дошка вчителя", "teacher_pointer_clear": "Прибрати покажчик учителя",
        "teacher_coordinates": "Перемкнути координати", "teacher_orientation": "Перевернути дошку",
        "teacher_event": "Прочитати останню дію учня", "classes_screen": "Класи та учні",
        "settings_screen": "Налаштування", "help_screen": "Клавіатура і довідка",
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


def build_full_product_menu_spec(
    registry: ActionRegistry,
    *,
    language: UILanguage | str,
) -> tuple[NativeTopMenuSpec, ...]:
    if not isinstance(registry, ActionRegistry):
        raise TypeError("native menu registry must be ActionRegistry")
    lang = _language(language)
    text = _TEXT[lang]

    def action(label_key: str, action_id: str) -> NativeMenuItemSpec:
        registry.definition(action_id)
        label = text[label_key]
        binding = registry.get_binding(action_id)
        if binding:
            label = f"{label}\t{binding}"
        return NativeMenuItemSpec(NativeMenuItemKind.ACTION, label, action_id=action_id)

    separator = NativeMenuItemSpec(NativeMenuItemKind.SEPARATOR)
    host_exit = NativeMenuItemSpec(NativeMenuItemKind.HOST, text["exit"], host_command="app.exit")
    rows = {
        "file": (action("open_pgn", "pgn.open"), action("import_library", "library.import"), action("export_pgn", "pgn.export_selection"), separator, host_exit),
        "game": (action("board_game", "screen.board"), action("standard", "move.standard"), action("empty", "move.empty"), separator, action("undo", "edit.undo"), action("redo", "edit.redo")),
        "position": (action("position_tools", "screen.board"), action("move_input", "board.input"), action("history_go", "history.go_to_move"), action("history_previous", "history.previous"), action("history_next", "history.next")),
        "pgn": (action("pgn_screen", "screen.pgn"), action("open_pgn", "pgn.open"), action("previous_game", "pgn.previous_game"), action("next_game", "pgn.next_game"), action("copy_pgn", "pgn.copy_selection"), action("export_pgn", "pgn.export_selection")),
        "library": (action("library_screen", "screen.library"), action("library_search", "library.search"), action("library_reset", "library.reset_filters"), action("library_open", "library.open_game")),
        "import": (action("import_library", "library.import"),),
        "export": (action("library_export", "library.export"), action("export_pgn", "pgn.export_selection")),
        "engine": (action("analysis_screen", "screen.analysis"), action("analysis_restart", "analysis.restart"), action("analysis_lock", "analysis.lock_target"), action("analysis_return", "analysis.return")),
        "analysis": (action("previous_pv", "analysis.previous_pv"), action("next_pv", "analysis.next_pv"), action("explore_pv", "analysis.explore_pv"), separator, action("insert_move", "analysis.insert_move"), action("insert_line", "analysis.insert_line")),
        "books": (action("books_screen", "screen.books"), action("book_previous_heading", "book.previous_heading"), action("book_next_heading", "book.next_heading"), action("book_next_position", "book.next_position"), action("book_next_game", "book.next_game"), action("book_bookmark", "book.bookmark"), action("book_open_position", "book.open_position"), action("book_return", "book.return")),
        "training": (action("training_screen", "screen.training"), action("training_hint", "training.hint"), action("training_reveal", "training.reveal_solution"), action("training_retry", "training.retry"), action("training_reset", "training.reset")),
        "teacher": (action("teacher_screen", "screen.teacher"), action("teacher_pointer_clear", "teacher.pointer_clear"), action("teacher_coordinates", "teacher.coordinates_toggle"), action("teacher_orientation", "teacher.orientation_toggle"), action("teacher_event", "teacher.read_student_event"), action("classes_screen", "screen.classes")),
        "settings": (action("settings_screen", "screen.settings"),),
        "help": (action("help_screen", "screen.help"),),
    }
    return tuple(
        NativeTopMenuSpec(menu_id, text[f"top.{menu_id}"], tuple(rows[menu_id]))
        for menu_id in _TOP_ORDER
    )


class FullProductNativeMenuController:
    def __init__(
        self,
        adapter: FullProductWebViewAdapter,
        command_sink: Callable[[WebViewCommand], Any],
        *,
        exit_callback: Callable[[], Any],
        current_focus_provider: Callable[[], str] | None = None,
    ) -> None:
        if not isinstance(adapter, FullProductWebViewAdapter):
            raise TypeError("native menu adapter must be FullProductWebViewAdapter")
        if not callable(command_sink) or not callable(exit_callback):
            raise TypeError("native menu callbacks must be callable")
        if current_focus_provider is not None and not callable(current_focus_provider):
            raise TypeError("native menu focus provider must be callable")
        self._adapter = adapter
        self._command_sink = command_sink
        self._exit_callback = exit_callback
        self._focus_provider = current_focus_provider or (lambda: "")

    def spec(self) -> tuple[NativeTopMenuSpec, ...]:
        return build_full_product_menu_spec(
            self._adapter.registry,
            language=self._adapter.shell.language,
        )

    def activate(self, item: NativeMenuItemSpec) -> WebViewCommand | None:
        if not isinstance(item, NativeMenuItemSpec):
            raise TypeError("native menu activation requires NativeMenuItemSpec")
        if item.kind is NativeMenuItemKind.SEPARATOR:
            raise ValueError("native menu separator cannot be activated")
        if item.kind is NativeMenuItemKind.HOST:
            self._exit_callback()
            return None
        focus = self._focus_provider()
        if not isinstance(focus, str):
            raise TypeError("native menu focus provider must return text")
        command = self._adapter.activate_action(
            item.action_id,
            current_focus_id=focus,
        )
        self._command_sink(command)
        return command


def install_full_product_windows_native_menu(
    window: Any,
    controller: FullProductNativeMenuController,
) -> bool:
    """Attach the extended native MenuStrip to the real WebView2 owner form."""
    if not isinstance(controller, FullProductNativeMenuController):
        raise TypeError("native menu controller is invalid")
    try:
        import clr  # type: ignore

        clr.AddReference("System.Windows.Forms")
        from System import Action  # type: ignore
        from System.Windows.Forms import (  # type: ignore
            AccessibleRole,
            DockStyle,
            MenuStrip,
            ToolStripMenuItem,
            ToolStripSeparator,
        )
    except Exception:
        return False

    form = _resolve_windows_host_form(window)
    if form is None:
        return False
    handlers: list[Any] = []

    def item(spec: NativeMenuItemSpec) -> Any:
        if spec.kind is NativeMenuItemKind.SEPARATOR:
            return ToolStripSeparator()
        menu_item = ToolStripMenuItem(spec.label)

        def on_click(sender, event, entry=spec):
            controller.activate(entry)

        handlers.append(on_click)
        menu_item.Click += on_click
        return menu_item

    menu = MenuStrip()
    menu.Name = "AccessibleChessFullProductMenu"
    menu.AccessibleName = "Application menu" if controller._adapter.shell.language is UILanguage.EN else "Меню програми"
    menu.AccessibleRole = AccessibleRole.MenuBar
    menu.Dock = DockStyle.Top
    menu.TabStop = False
    menu.Visible = True
    menu.Enabled = True
    for top_spec in controller.spec():
        top = ToolStripMenuItem(top_spec.label)
        for child in top_spec.items:
            top.DropDownItems.Add(item(child))
        menu.Items.Add(top)

    setattr(window, "_accessible_chess_native_menu", menu)
    setattr(window, "_accessible_chess_native_menu_handlers", handlers)
    setattr(window, "_accessible_chess_native_menu_host", form)
    setattr(window, "_accessible_chess_native_menu_controller", controller)

    def attach() -> None:
        form.SuspendLayout()
        try:
            stale = None
            for control in list(form.Controls):
                if getattr(control, "Name", "") in {
                    "AccessibleChessMainMenu",
                    "AccessibleChessFullProductMenu",
                }:
                    stale = control
                    break
            if stale is not None and not _same_managed_object(stale, menu):
                form.Controls.Remove(stale)
                try:
                    stale.Dispose()
                except Exception:
                    pass
            form.MainMenuStrip = menu
            form.Controls.Add(menu)
            menu.BringToFront()
            form.PerformLayout()
            if not _same_managed_object(getattr(menu, "Parent", None), form):
                raise RuntimeError("full-product native menu attached to wrong owner")
            if not _same_managed_object(getattr(form, "MainMenuStrip", None), menu):
                raise RuntimeError("full-product native menu is not the host MainMenuStrip")
        finally:
            form.ResumeLayout(True)

    try:
        if getattr(form, "InvokeRequired", False):
            form.Invoke(Action(attach))
        else:
            attach()
    except Exception:
        return False
    return True
