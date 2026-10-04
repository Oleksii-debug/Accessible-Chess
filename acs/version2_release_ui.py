from __future__ import annotations

"""Production-facing Version 2 WebView composition over the frozen Stage 1 board.

The Version 2 host deliberately keeps the existing ``web/index.html`` and its
64-square board as the only chess UI/state authority.  It adds the accepted V2
shell/PGN/Library/Books projections around that document and routes native menu
commands through the same V2 adapter.  No chess, PGN, database or Book semantics
live in this module.
"""

from collections.abc import Mapping
from dataclasses import asdict
from functools import wraps
import threading
from typing import Any, Callable

from .chesscore import Board
from .full_product_native_menu import install_full_product_windows_native_menu
from .full_product_ui_shell import UILanguage
from .stage1_release_ui import Stage1ReleaseAccessibleChessAPI, _asset_root
from .ui_native_menu import _resolve_windows_host_form
from .ui_review_adapter import ReviewView
from .version2_profile import VERSION2_FULL_PRODUCT_ACTION_IDS, Version2NativeMenuController


class Version2ReleaseAccessibleChessAPI(Stage1ReleaseAccessibleChessAPI):
    """One pywebview API object for the frozen board and accepted V2 shell.

    Stage 1 public methods remain inherited unchanged.  V2 methods are explicit
    additions so pywebview does not need a second ``js_api`` object and therefore
    cannot accidentally create a second board/engine authority.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._ui_thread = threading.get_ident()
        self._ui_owner: Any | None = None
        self._ui_action: Callable | None = None
        self._ui_closed = False
        super().__init__(*args, **kwargs)
        self._version2_application: Any | None = None
        self._version2_language_refresh: Callable[[], bool] | None = None
        self._external_review_fen: str | None = None

    def _bind_ui_owner(self, owner: Any, *, action_factory: Callable | None = None) -> None:
        """Trusted host seam: called on the actual Form thread before DB creation."""
        if owner is None or getattr(owner, "InvokeRequired", True):
            raise RuntimeError("Version 2 native UI owner thread is required")
        if self._ui_owner is not None and self._ui_owner is not owner:
            raise RuntimeError("Version 2 native UI owner is already bound")
        if action_factory is None:
            from System import Action  # type: ignore
            action_factory = Action
        self._ui_owner, self._ui_action = owner, action_factory
        self._ui_thread = threading.get_ident()

    def _invoke_ui(self, callback: Callable[[], Any]) -> Any:
        if self._ui_closed:
            raise RuntimeError("Version 2 application is closed")
        if threading.get_ident() == self._ui_thread:
            return callback()
        owner, action = self._ui_owner, self._ui_action
        if owner is None or action is None or getattr(owner, "IsDisposed", True):
            raise RuntimeError("Version 2 native UI is unavailable")
        results, errors = [], []

        def invoke() -> None:
            try:
                if self._ui_closed:
                    raise RuntimeError("Version 2 application is closed")
                results.append(callback())
            except Exception as error:
                errors.append(error)

        owner.Invoke(action(invoke))
        if errors:
            raise errors[0]
        if not results:
            raise RuntimeError("Version 2 UI command did not complete")
        return results[0]

    def bind_version2_application(self, application: Any) -> None:
        if self._version2_application is not None and self._version2_application is not application:
            raise RuntimeError("Version 2 application is already bound")
        for name in (
            "snapshot",
            "browser_command",
            "drain_events",
            "record_focus",
            "native_command",
            "shutdown",
        ):
            if not callable(getattr(application, name, None)):
                raise TypeError("Version 2 application host contract is incomplete")
        if getattr(application, "adapter", None) is None:
            raise TypeError("Version 2 application requires its accepted WebView adapter")
        self._version2_application = application

    def bind_version2_language_refresh(self, callback: Callable[[], bool]) -> None:
        """Bind the owner-host refresh used to rebuild localized native menus."""

        if not callable(callback):
            raise TypeError("Version 2 language refresh callback must be callable")
        if self._version2_language_refresh is not None and self._version2_language_refresh is not callback:
            raise RuntimeError("Version 2 language refresh callback is already bound")
        self._version2_language_refresh = callback

    @staticmethod
    def _sync_version2_language(application: Any, language: UILanguage) -> None:
        """Apply one presentation language to every currently materialized V2 surface."""

        if not isinstance(language, UILanguage):
            raise TypeError("Version 2 language must be UILanguage")
        shell = getattr(application, "shell", None)
        set_shell_language = getattr(shell, "set_language", None)
        if not callable(set_shell_language):
            raise TypeError("Version 2 shell cannot change language")
        set_shell_language(language)

        for bridge_name in ("pgn", "library", "books"):
            bridge = getattr(application, bridge_name, None)
            if bridge is None:
                continue
            projection = getattr(bridge, "projection", None)
            set_projection_language = getattr(projection, "set_language", None)
            if not callable(set_projection_language):
                raise TypeError(f"Version 2 {bridge_name} surface cannot change language")
            set_projection_language(language)

    @staticmethod
    def _queue_version2_language_refresh(application: Any) -> None:
        """Wake the existing V2 event poller without creating a spoken announcement."""

        events = getattr(application, "_events", None)
        append = getattr(events, "append", None)
        if not callable(append):
            raise TypeError("Version 2 application event queue is unavailable")
        append({"kind": "language", "payload": {}})

    @staticmethod
    def _restore_settings_language_memory(settings: Any, language: str) -> None:
        """Undo Settings.set()'s in-memory assignment when its atomic save fails."""

        data = getattr(settings, "data", None)
        if isinstance(data, dict):
            data["language"] = language

    @classmethod
    def _rollback_settings_language(cls, settings: Any, language: str) -> None:
        if settings is None:
            return
        try:
            settings.set("language", language)
        except Exception:
            cls._restore_settings_language_memory(settings, language)

    def _language_error(self, language: str) -> dict[str, Any]:
        return self._error(
            "Language could not be changed."
            if language == "en"
            else "Не вдалося змінити мову."
        )

    def set_language(self, lang: str) -> dict[str, Any]:
        """Persist first, then atomically converge every live V2 presentation surface."""

        if type(lang) is not str:
            return super().set_language(lang)
        target = lang.strip().lower()
        if target not in {"uk", "en"}:
            return super().set_language(lang)

        previous = self.lang
        settings = getattr(self, "_settings", None)
        application = self._version2_application

        if settings is not None:
            try:
                settings.set("language", target)
            except Exception:
                self._restore_settings_language_memory(settings, previous)
                return self._language_error(previous)

        try:
            result = super().set_language(target)
        except Exception:
            self._rollback_settings_language(settings, previous)
            return self._language_error(previous)

        if not result.get("ok"):
            self._rollback_settings_language(settings, previous)
            return result

        try:
            language = UILanguage(target)
            if application is not None:
                self._sync_version2_language(application, language)
            if self._version2_language_refresh is not None:
                if self._version2_language_refresh() is not True:
                    raise RuntimeError("Version 2 native menu language refresh failed")
            if application is not None:
                self._queue_version2_language_refresh(application)
        except Exception:
            try:
                super().set_language(previous)
            except Exception:
                pass
            if application is not None:
                try:
                    self._sync_version2_language(application, UILanguage(previous))
                except Exception:
                    pass
            if self._version2_language_refresh is not None:
                try:
                    self._version2_language_refresh()
                except Exception:
                    pass
            self._rollback_settings_language(settings, previous)
            if application is not None:
                try:
                    self._queue_version2_language_refresh(application)
                except Exception:
                    pass
            return self._language_error(previous)

        return result

    def _version2(self) -> Any:
        application = self._version2_application
        if application is None:
            raise RuntimeError("Version 2 application is not bound")
        return application

    @staticmethod
    def _keymap_context_name(value: object) -> str:
        raw = getattr(value, "value", value)
        return str(raw or "").strip().lower()

    def _v2_keyboard_fallback_contexts(self, requested_context: object) -> tuple[str, ...]:
        """Map the inherited key owner onto the active V2 registry contexts.

        The shipped Stage 1 document remains the only keyboard-capture engine.
        This seam changes only central registry lookup order after an exact Stage 1
        context miss: active V2 route context first, then the existing GLOBAL
        fallback.  It never parses or normalizes a second shortcut map.
        """

        if self._version2_application is None:
            return ()
        requested = self._keymap_context_name(requested_context)
        application = self._version2()
        contexts: list[str] = []

        # The frozen document probes ANALYSIS -> HISTORY -> DOCUMENT for every
        # non-board keystroke.  Each legacy registry lookup includes GLOBAL on its
        # own, so active V2 route context must be considered before that GLOBAL
        # result during every probe or a GLOBAL remap would mask DATABASE/BOOK
        # bindings before the document probe is reached.
        if requested in {"analysis", "history", "document"}:
            shell = getattr(application, "shell", None)
            route = getattr(getattr(shell, "current_route", None), "route_id", "")
            route_context = {
                "pgn": "document",
                "library": "database",
                "books": "book_reader",
            }.get(route)
            if route_context:
                contexts.append(route_context)
        elif requested == "board":
            book_workflow = getattr(application, "book_workflow", None)
            if bool(getattr(book_workflow, "active", False)):
                contexts.append("book_reader")
            elif bool(getattr(application, "pgn_board_active", False)):
                contexts.append("document")

        unique: list[str] = []
        for context in contexts:
            if context != requested and context not in unique:
                unique.append(context)
        return tuple(unique)

    def _resolve_v2_keyboard_value(
        self,
        resolver: Callable[[str, str], dict[str, Any] | None],
        context: str,
        value: str,
    ) -> dict[str, Any] | None:
        """Prefer exact Stage 1, then active V2 route, then GLOBAL fallback."""

        requested = self._keymap_context_name(context)
        direct = resolver(context, value)
        if direct is not None and self._keymap_context_name(direct.get("context")) == requested:
            return direct

        global_fallback = (
            direct
            if direct is not None and self._keymap_context_name(direct.get("context")) == "global"
            else None
        )
        for fallback in self._v2_keyboard_fallback_contexts(requested):
            resolved = resolver(fallback, value)
            if resolved is None:
                continue
            resolved_context = self._keymap_context_name(resolved.get("context"))
            if resolved_context == fallback:
                return resolved
            if global_fallback is None and resolved_context == "global":
                global_fallback = resolved
        return global_fallback if global_fallback is not None else direct

    def keymap_resolve_binding(self, context: str, binding: str) -> dict[str, Any] | None:
        """Resolve the one shared keymap using dynamic V2 route precedence."""

        return self._resolve_v2_keyboard_value(
            super().keymap_resolve_binding,
            context,
            binding,
        )

    def keymap_resolve_alias(self, context: str, alias: str) -> dict[str, Any] | None:
        """Keep command aliases on the same dynamic context rule as bindings."""

        return self._resolve_v2_keyboard_value(
            super().keymap_resolve_alias,
            context,
            alias,
        )

    def dispatch_action(self, action_id: str, square: str | None = None) -> dict[str, Any]:
        """Route registered V2 keyboard actions through the canonical V2 adapter/router.

        ``web/index.html`` stays the one keyboard owner. Its ``apiAction`` helper
        renders every result as Stage 1 state, so successful V2 dispatch returns a
        complete current Stage 1 projection while the V2 application publishes its
        own route/domain event through the same command path used by native menu.
        """

        if (
            self._version2_application is not None
            and isinstance(action_id, str)
            and action_id in VERSION2_FULL_PRODUCT_ACTION_IDS
        ):
            if square not in (None, ""):
                return self._error(
                    "Дія Version 2 не приймає поле дошки."
                    if self.lang == "uk"
                    else "Version 2 action does not accept a board square."
                )
            application = self._version2()
            command = application.adapter.activate_action(
                action_id,
                current_focus_id=str(getattr(application, "_focus", "")),
            )
            application.native_command(command)
            payload = dict(command.payload)
            if command.kind == "error":
                return self._error(str(payload.get("message", "")))
            result = self._ok("")
            result["v2"] = asdict(command)
            return result
        return super().dispatch_action(action_id, square)

    def _external_review_owned(self) -> bool:
        """Whether a PGN/Book workflow still owns the external Board review.

        Ownership persists while the user temporarily visits another V2 route.
        Explicit PGN/Book Return ends it.  Keeping this separate from visible
        Board projection prevents a global/native mutation from changing the
        hidden live game while the external review session is still open.
        """

        if self._external_review_fen is None:
            return False
        application = self._version2_application
        if application is None:
            return False
        if getattr(application, "pgn_board_active", False) is True:
            return True
        workflow = getattr(application, "book_workflow", None)
        return workflow is not None and getattr(workflow, "active", False) is True

    def _external_review_active(self) -> bool:
        """Whether the V2 shell is visibly projecting external review on Board."""

        if not self._external_review_owned():
            return False
        application = self._version2_application
        shell = getattr(application, "shell", None)
        route = getattr(getattr(shell, "current_route", None), "route_id", "")
        return route == "board"

    def project_review_fen(self, fen: str) -> dict[str, Any]:
        """Project an external canonical position without mutating the live game.

        PGN and Book review are presentation state.  They must drive the same
        accessible 64-square board while leaving ``self.board``, SAN history,
        ReviewHistory identity and engine-game ownership untouched.  Validation
        is delegated to the canonical Board implementation; malformed input is
        rejected before the cached projection changes.
        """

        if type(fen) is not str or not fen.strip():
            return {"ok": False}
        try:
            canonical = Board(fen).fen()
        except Exception:
            return {"ok": False}
        self._external_review_fen = canonical
        return {"ok": True}

    def _display_review(self) -> ReviewView:
        if self._external_review_active():
            return ReviewView(
                fen=str(self._external_review_fen),
                ply=0,
                node_id=-1,
                at_start=False,
                at_end=False,
                status=(
                    "Зовнішня позиція для перегляду."
                    if self.lang == "uk"
                    else "External review position."
                ),
                last_move=None,
            )
        return super()._display_review()

    def _display_board(self) -> Board:
        if self._external_review_active():
            return Board(str(self._external_review_fen))
        return super()._display_board()

    def _visible_ply_count(self) -> int:
        if self._external_review_active():
            return 0
        return super()._visible_ply_count()

    def _at_history_end(self) -> bool:
        if self._external_review_owned():
            return False
        return super()._at_history_end()

    def _analysis_origin_matches(self) -> bool:
        if self._external_review_owned():
            return False
        return super()._analysis_origin_matches()

    def _external_review_mutation_error(self) -> dict[str, Any]:
        return self._error(
            "Спочатку поверніться з перегляду документа."
            if self.lang == "uk"
            else "Return from document review first."
        )

    def make_move(self, text: str) -> dict[str, Any]:
        if self._external_review_owned():
            return self._external_review_mutation_error()
        return super().make_move(text)

    def activate_square(self, square: str) -> dict[str, Any]:
        if self._external_review_owned():
            return self._external_review_mutation_error()
        return super().activate_square(square)

    def undo(self) -> dict[str, Any]:
        if self._external_review_owned():
            return self._external_review_mutation_error()
        return super().undo()

    def redo(self) -> dict[str, Any]:
        if self._external_review_owned():
            return self._external_review_mutation_error()
        return super().redo()

    def new_game(self) -> dict[str, Any]:
        if self._external_review_owned():
            return self._external_review_mutation_error()
        return super().new_game()

    def clear_board(self) -> dict[str, Any]:
        if self._external_review_owned():
            return self._external_review_mutation_error()
        return super().clear_board()

    def set_fen(self, fen: str) -> dict[str, Any]:
        if self._external_review_owned():
            return self._external_review_mutation_error()
        return super().set_fen(fen)

    def set_position_text(self, text: str, turn: str | None = None) -> dict[str, Any]:
        if self._external_review_owned():
            return self._external_review_mutation_error()
        return super().set_position_text(text, turn)

    def set_turn(self, color: str) -> dict[str, Any]:
        if self._external_review_owned():
            return self._external_review_mutation_error()
        return super().set_turn(color)

    def start_engine_game(
        self,
        human_side: str = "white",
        level: int = 5,
        initial_minutes: int = 0,
        increment_seconds: int = 0,
    ) -> dict[str, Any]:
        if self._external_review_owned():
            return self._external_review_mutation_error()
        return super().start_engine_game(
            human_side,
            level,
            initial_minutes,
            increment_seconds,
        )

    def stop_engine_game(self) -> dict[str, Any]:
        if self._external_review_owned():
            return self._external_review_mutation_error()
        return super().stop_engine_game()

    def retry_engine_move(self) -> dict[str, Any]:
        if self._external_review_owned():
            return self._external_review_mutation_error()
        return super().retry_engine_move()

    def engine_takeback(self) -> dict[str, Any]:
        if self._external_review_owned():
            return self._external_review_mutation_error()
        return super().engine_takeback()

    def offer_draw_engine_game(self) -> dict[str, Any]:
        if self._external_review_owned():
            return self._external_review_mutation_error()
        return super().offer_draw_engine_game()

    def resign_engine_game(self) -> dict[str, Any]:
        if self._external_review_owned():
            return self._external_review_mutation_error()
        return super().resign_engine_game()

    def get_state(self) -> dict[str, Any]:
        state = super().get_state()
        if self._external_review_active():
            state["historyLength"] = 0
        return state

    def v2_snapshot(self) -> dict[str, object]:
        return self._version2().snapshot()

    def v2_browser_command(
        self,
        area: str,
        command: str,
        payload: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        return self._version2().browser_command(area, command, payload)

    def v2_drain_events(self) -> tuple[dict[str, object], ...]:
        return tuple(self._version2().drain_events())

    def v2_record_focus(self, token: str) -> None:
        self._version2().record_focus(token)

    def v2_board_dispatch(
        self,
        action_id: str,
        payload: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        """Delegate V2 board/global actions to the canonical Stage 1 API.

        The only payload accepted at this seam is an optional board square.  All
        richer V2 domain payloads remain owned by their format/library adapters.
        """

        if not isinstance(action_id, str) or not action_id.strip():
            raise ValueError("board action id is required")
        values = {} if payload is None else payload
        if not isinstance(values, Mapping):
            raise TypeError("board action payload must be a mapping")
        square: str | None = None
        if values:
            if set(values) != {"square"} or not isinstance(values.get("square"), str):
                raise ValueError("board action payload is not supported")
            square = str(values["square"])
        result = super().dispatch_action(action_id.strip(), square)
        if not isinstance(result, dict):
            raise RuntimeError("canonical board action returned an invalid result")
        if result.get("ok") is False:
            raise ValueError("canonical board action was rejected")
        return result


def _ui_method(method: Callable) -> Callable:
    @wraps(method)
    def invoke(self, *args, **kwargs):
        return self._invoke_ui(lambda: method(self, *args, **kwargs))
    return invoke


# pywebview invokes public API methods on background threads. Serialize the
# inherited board API as well as V2 commands on the same native owner, retaining
# signatures for pywebview's introspection and the original Stage 1 implementation.
for _name in dir(Version2ReleaseAccessibleChessAPI):
    _method = getattr(Version2ReleaseAccessibleChessAPI, _name)
    if not _name.startswith("_") and callable(_method):
        setattr(Version2ReleaseAccessibleChessAPI, _name, _ui_method(_method))


def _resource_sources() -> tuple[tuple[str, str], ...]:
    root = _asset_root() / "web"
    resources = (
        ("Stage 1 WebView bootstrap", root / "stage1_release_bootstrap.js"),
        ("Stage 1 board action bridge", root / "stage1_board_actions.js"),
        ("V2 PGN surface", root / "full_product_pgn.js"),
        ("V2 Library surface", root / "full_product_library.js"),
        ("V2 Books surface", root / "full_product_books_training.js"),
        ("V2 release bootstrap", root / "version2_release_bootstrap.js"),
    )
    output: list[tuple[str, str]] = []
    for label, path in resources:
        if not path.exists():
            raise RuntimeError(f"{label} not found in packaged resources.")
        output.append((label, path.read_text(encoding="utf-8")))
    return tuple(output)


def run_version2_release_window(
    api: Version2ReleaseAccessibleChessAPI,
    application: Any,
    runtime: Any | None = None,
    *,
    webview_module: Any | None = None,
    menu_installer: Callable[[Any, Any], bool] = install_full_product_windows_native_menu,
    file_runtime_factory: Callable[[object], Any] | None = None,
    loaded_hook: Callable[[Any], None] | None = None,
) -> None:
    """Run V2 on the original Stage 1 document and real Edge/WebView2 host."""

    if not isinstance(api, Version2ReleaseAccessibleChessAPI):
        raise TypeError("V2 release window requires Version2ReleaseAccessibleChessAPI")
    if not callable(menu_installer):
        raise TypeError("V2 native menu installer must be callable")
    if file_runtime_factory is not None and not callable(file_runtime_factory):
        raise TypeError("V2 file runtime factory must be callable or None")
    application_factory = application if callable(application) else None
    if application_factory is not None:
        application = None
    else:
        api.bind_version2_application(application)

    application_closed = False
    startup_errors: list[Exception] = []

    def close_application(*_args: Any) -> bool:
        nonlocal application_closed
        if application is not None and not application_closed:
            # A production native FormClosing guard shuts application-owned state
            # down while the owner Form is still alive.  The release loop only
            # records that completed shutdown here; it must never run it twice.
            if getattr(application, "_native_close_shutdown_complete", False):
                application_closed = True
            else:
                if not api._invoke_ui(application.shutdown):
                    return False
                application_closed = True
        api._ui_closed = True
        return True

    primary_error: BaseException | None = None
    cleanup_error: BaseException | None = None

    try:
        # Keep every startup step after application/runtime composition inside the
        # same lifecycle boundary.  This selectively preserves #476's startup
        # cleanup contract on the current V2 runtime without reverting newer UI
        # ownership, close guards or external-review behavior.
        html = _asset_root() / "web" / "index.html"
        if not html.exists():
            raise RuntimeError("Accessible HTML UI not found in packaged resources.")
        sources = _resource_sources()

        if webview_module is None:
            import webview as webview_module  # type: ignore[no-redef]

        window = webview_module.create_window(
            "Accessible Chess",
            url=str(html),
            js_api=api,
            width=1150,
            height=820,
            min_size=(800, 600),
            text_select=True,
        )

        def exit_application() -> None:
            destroy = getattr(window, "destroy", None)
            if callable(destroy):
                destroy()

        native_files: Any | None = None

        def window_closing_without_destructive_shutdown(*_args: Any) -> bool:
            # pywebview's closing event can run before or after later WinForms
            # FormClosing subscribers.  Once the native guard exists, doing cleanup
            # here would make refusal too late and would duplicate the accepted path.
            if application is not None and getattr(
                application, "_native_unsaved_close_guard", None
            ) is not None:
                return True
            return close_application()

        def install_menu_on_native_host(*_args: Any) -> None:
            nonlocal application, native_files
            if application_factory is not None:
                owner = _resolve_windows_host_form(window)
                api._bind_ui_owner(owner)
                application = application_factory()
                api.bind_version2_application(application)
            elif api._ui_owner is None:
                assert_thread = getattr(application, "_assert_thread", None)
                if callable(assert_thread):
                    assert_thread()
            controller = Version2NativeMenuController(
                application.adapter,
                application.native_command,
                exit_callback=exit_application,
                current_focus_provider=lambda: str(getattr(application, "_focus", "")),
            )
            if not menu_installer(window, controller):
                raise RuntimeError("Accessible Version 2 native Windows menu could not be attached.")
            if api._version2_language_refresh is None:
                api.bind_version2_language_refresh(
                    lambda: bool(menu_installer(window, controller))
                )
            if file_runtime_factory is None or native_files is not None:
                return
            owner = getattr(window, "_accessible_chess_native_menu_host", None)
            if owner is None:
                raise RuntimeError("Accessible Version 2 native Windows owner could not be resolved.")
            native_files = file_runtime_factory(owner)
            application.bind_files(native_files)

        def start_native_host(*_args: Any) -> None:
            try:
                install_menu_on_native_host()
            except Exception as error:
                startup_errors.append(error)
                try:
                    close_application()
                finally:
                    window.destroy()
                raise

        def install_release_web_contract(*_args: Any) -> None:
            if startup_errors:
                return
            for _label, source in sources:
                window.evaluate_js(source)
            if loaded_hook is not None:
                loaded_hook(window)

        window.events.before_show += start_native_host
        window.events.loaded += install_release_web_contract
        closing = getattr(window.events, "closing", None)
        if closing is not None:
            window.events.closing += window_closing_without_destructive_shutdown
        webview_module.start(gui="edgechromium", private_mode=True)
        if startup_errors:
            raise startup_errors[0]
    except BaseException as error:
        # If native startup recorded the real owner failure but its immediate
        # shutdown also failed, keep the original startup failure primary.
        primary_error = startup_errors[0] if startup_errors else error

    # Cleanup is ordered and exhaustive.  The first failure remains observable,
    # while later cleanup failures never replace an already-active Product/runtime
    # failure.  This closes the exact failure-precedence gap proven by #588.
    try:
        if application is not None and not application_closed:
            close_application()
    except BaseException as error:
        cleanup_error = error

    try:
        Stage1ReleaseAccessibleChessAPI.close_analysis(api)
    except BaseException as error:
        if cleanup_error is None:
            cleanup_error = error

    try:
        if runtime is not None:
            runtime.close()
    except BaseException as error:
        if cleanup_error is None:
            cleanup_error = error

    if primary_error is not None:
        raise primary_error
    if cleanup_error is not None:
        raise cleanup_error


__all__ = [
    "Version2ReleaseAccessibleChessAPI",
    "run_version2_release_window",
]
