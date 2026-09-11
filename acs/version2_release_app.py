from __future__ import annotations

"""Production composition root for the Accessible Chess Version 2 candidate.

This module reuses the same release engine/sound/settings components as Stage 1,
adds the accepted V2 application services, and binds trusted Windows file dialogs
only after pywebview exposes the real native owner Form.  It creates no chess or
format semantics of its own.
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable

from .acsdb import AcsDatabase
from .analysis_service import AnalysisService
from .book_progress_store import BookProgressStore
from .continuous_analysis import ContinuousAnalysisService
from .engine_assisted_workflows import EngineAssistedWorkflowService
from .engine_play_service import EnginePlayService
from .full_product_ui_shell import UILanguage
from .release_app import _sound_cache_dir, _user_root
from .settings import Settings
from .sound_runtime import GameSoundRuntime, SoundRuntime, SoundRuntimeSettings
from .sound_windows import PackagedSoundAssetResolver, WindowsSoundPlaybackAdapter
from .stockfish_runtime import StockfishRuntime, StockfishRuntimeConfig
from .version2_application import Version2Application
from .version2_release_ui import Version2ReleaseAccessibleChessAPI, run_version2_release_window
from .version2_upgrade import UserDataLayout, Version2UpgradeCoordinator
from .version2_windows_host_runtime import Version2WindowsFileWorkflowRuntime
from .version2_windows_native_dialog_ownership import Version2OwnedWindowsFileDialogs
from .webapp_keymap import _asset_root


class _Version2OwnedBookDialogs(Version2OwnedWindowsFileDialogs):
    """Owner-bound Open and release-lifecycle dialogs for supported books/PGN."""

    def open_book(self) -> Path | None:
        DialogResult, OpenFileDialog, _ = self._load_forms()
        dialog = OpenFileDialog()
        try:
            dialog.Title = "Open chess book"
            dialog.Filter = (
                "Supported books (*.html;*.htm;*.xhtml;*.txt;*.md;*.markdown)|"
                "*.html;*.htm;*.xhtml;*.txt;*.md;*.markdown|"
                "HTML books (*.html;*.htm;*.xhtml)|*.html;*.htm;*.xhtml|"
                "Text and Markdown (*.txt;*.md;*.markdown)|*.txt;*.md;*.markdown"
            )
            dialog.CheckFileExists = True
            dialog.CheckPathExists = True
            dialog.Multiselect = False
            return self._selected(dialog, dialog.ShowDialog(), DialogResult.OK)
        finally:
            dialog.Dispose()

    def confirm_discard_unsaved_pgn_on_exit(self) -> bool:
        """Confirm destructive application close on the exact native owner Form."""

        owner = self._dialog_owner.resolve()
        DialogResult, _, _ = self._forms_loader()
        MessageBox, MessageBoxButtons, MessageBoxIcon = self._message_box_loader()
        result = MessageBox.Show(
            owner,
            "The current PGN has unsaved changes. Exit without saving these changes?",
            "Unsaved PGN changes",
            MessageBoxButtons.YesNo,
            MessageBoxIcon.Warning,
        )
        return result == DialogResult.Yes


def _install_unsaved_pgn_close_guard(
    application: Version2Application,
    owner_control: object,
    dialogs: object,
):
    """Own confirmation and accepted cleanup at one native FormClosing boundary.

    The real WinForms ``FormClosing`` event is the authority for File > Exit,
    Alt+F4, title-bar X and programmatic host close.  Dirty refusal or confirmation
    failure sets ``Cancel`` before application shutdown is touched.  Clean or
    explicitly accepted closes run the existing application shutdown while the
    owner Form and UI thread are still alive.  The release loop observes the
    completion marker and must not call application shutdown a second time.
    """

    if owner_control is None:
        raise RuntimeError("Version 2 Windows owner control is unavailable")
    confirmation = getattr(dialogs, "confirm_discard_unsaved_pgn_on_exit", None)
    if not callable(confirmation):
        raise TypeError("Version 2 exit confirmation is unavailable")
    shutdown = getattr(application, "shutdown", None)
    if not callable(shutdown):
        raise TypeError("Version 2 application shutdown is unavailable")
    closing_event = getattr(owner_control, "FormClosing", None)
    if closing_event is None:
        raise RuntimeError("Version 2 native owner does not expose FormClosing")

    existing = getattr(application, "_native_unsaved_close_guard", None)
    if existing is not None:
        raise RuntimeError("Version 2 unsaved close guard is already installed")

    state = {"handling": False, "shutdown_complete": False}

    def cancel_close(event: object) -> None:
        try:
            setattr(event, "Cancel", True)
        except Exception as error:
            raise RuntimeError("Version 2 native close cannot be cancelled") from error

    def on_form_closing(_sender: object, event: object) -> None:
        if state["shutdown_complete"]:
            return
        if state["handling"]:
            cancel_close(event)
            return

        state["handling"] = True
        try:
            try:
                session = getattr(application, "session", None)
                dirty = session is not None and bool(getattr(session, "dirty"))
            except Exception:
                dirty = True

            if dirty:
                try:
                    discard = confirmation() is True
                except Exception:
                    cancel_close(event)
                    return
                if not discard:
                    cancel_close(event)
                    return

            try:
                shutdown_complete = shutdown() is True
            except Exception as error:
                setattr(application, "_native_close_shutdown_error", error)
                cancel_close(event)
                return
            if not shutdown_complete:
                cancel_close(event)
                return

            state["shutdown_complete"] = True
            setattr(application, "_native_close_shutdown_complete", True)
        finally:
            state["handling"] = False

    owner_control.FormClosing += on_form_closing
    application._native_unsaved_close_guard = on_form_closing
    return on_form_closing


def _install_close_guard_or_shutdown(
    file_runtime: object,
    application: Version2Application,
    owner_control: object,
    dialogs: object,
):
    """Install the close guard or synchronously retire the unbound runtime.

    The native file runtime is allocated before it can be bound to the application.
    If FormClosing/owner/dialog validation fails at that boundary, the outer release
    cleanup cannot see that runtime.  Close it here before propagating the original
    guard failure; never leave a worker/pump ownerless during startup.
    """

    try:
        _install_unsaved_pgn_close_guard(application, owner_control, dialogs)
    except Exception:
        cleanup_error = None
        try:
            shutdown_runtime = getattr(file_runtime, "shutdown", None)
            if not callable(shutdown_runtime) or shutdown_runtime() is not True:
                cleanup_error = RuntimeError(
                    "Version 2 unbound native runtime did not shut down"
                )
        except Exception as exc:
            cleanup_error = exc
        if cleanup_error is not None:
            raise RuntimeError(
                "Version 2 unbound native runtime cleanup failed after close-guard installation failure"
            ) from cleanup_error
        raise
    return file_runtime


def _copy_text_to_windows_clipboard(value: str) -> None:
    if not isinstance(value, str):
        raise TypeError("clipboard text must be text")
    import clr  # type: ignore

    clr.AddReference("System.Windows.Forms")
    from System.Windows.Forms import Clipboard  # type: ignore

    Clipboard.SetText(value)


def _install_host_confirmed_document(application: Version2Application, session: object) -> Any:
    """Install a PGN after the trusted host already confirmed dirty replacement.

    ``Version2WindowsFileActionDelegate`` owns the modal confirmation before it
    invokes this callback.  Temporarily accepting the same replacement prevents a
    second contradictory confirmation inside ``Version2Application.set_document``.
    Browser callers never receive this callback.
    """

    previous = application.confirm_document_replace
    application.confirm_document_replace = lambda: True
    try:
        return application.set_document(session)
    finally:
        application.confirm_document_replace = previous


def _share_v2_action_registry(
    api: Version2ReleaseAccessibleChessAPI,
    application: Version2Application,
):
    """Make Stage 1 keymap editing and V2 routing use one persisted registry.

    Existing Stage 1 remaps are copied into the wider V2 registry first.  The
    KeymapService then points at that exact object, so keyboard resolution,
    WebView commands and the native Windows menu cannot drift into parallel
    command maps during the V2 release.
    """

    source = api.keymap_service.editor.registry
    profile = source.to_profile()
    bindings = profile.get("bindings", {})
    aliases = profile.get("aliases", {})
    if not isinstance(bindings, Mapping) or not isinstance(aliases, Mapping):
        raise ValueError("stored keymap profile is invalid")

    registry = application.adapter.registry
    for action_id, value in bindings.items():
        try:
            registry.definition(action_id)
        except KeyError:
            continue
        registry.set_binding(action_id, value, allow_warnings=True)
    for action_id, value in aliases.items():
        try:
            registry.definition(action_id)
        except KeyError:
            continue
        registry.set_alias(action_id, value)

    api.keymap_service.editor.registry = registry
    return registry


def _version2_user_data_layout(
    *,
    data_root: str | Path | None = None,
    settings_path: str | Path | None = None,
) -> UserDataLayout:
    """Resolve the one canonical V2 user-data root used by all persistent writers."""

    explicit_settings = Path(settings_path) if settings_path is not None else None
    if data_root is None:
        if explicit_settings is None:
            return UserDataLayout(_user_root())
        return UserDataLayout(explicit_settings.parent, settings_name=explicit_settings.name)

    root = Path(data_root)
    if explicit_settings is None:
        return UserDataLayout(root)
    if explicit_settings.parent != root:
        raise ValueError("settings_path must belong to the Version 2 data_root")
    return UserDataLayout(root, settings_name=explicit_settings.name)


def _prepare_version2_user_data(
    *,
    data_root: str | Path | None = None,
    settings_path: str | Path | None = None,
    coordinator_factory: Callable[[UserDataLayout], Any] = Version2UpgradeCoordinator,
) -> UserDataLayout:
    """Recover/upgrade V2 state before any normal settings or database writer opens."""

    if not callable(coordinator_factory):
        raise TypeError("coordinator_factory must be callable")
    layout = _version2_user_data_layout(data_root=data_root, settings_path=settings_path)
    coordinator = coordinator_factory(layout)
    run = getattr(coordinator, "run", None)
    if not callable(run):
        raise TypeError("Version 2 upgrade coordinator must expose run()")
    run()
    return layout


def create_version2_release_application(
    *,
    application_dir: str | Path | None = None,
    runtime_factory: Callable[[StockfishRuntimeConfig], Any] = StockfishRuntime,
    sound_playback: Any | None = None,
    settings_path: str | Path | None = None,
    data_root: str | Path | None = None,
    copy_text: Callable[[str], Any] = _copy_text_to_windows_clipboard,
    defer_ui: bool = False,
):
    """Compose one engine provider plus the persistent V2 application state.

    Persistent state is recovered/upgraded before any normal ``Settings`` or
    ``AcsDatabase`` writer opens.  The returned native-runtime factory must then be
    called on the actual Windows UI thread with the exact pywebview owner control.
    With ``defer_ui=True`` the second return value is a one-shot application
    factory, invoked by the window's synchronous before_show event on its native
    STA thread. Diagnostics can keep the eager, calling-thread composition.
    """

    layout = _prepare_version2_user_data(
        data_root=data_root,
        settings_path=settings_path,
    )
    app_dir = Path(application_dir) if application_dir is not None else _asset_root()
    engine_runtime = runtime_factory(StockfishRuntimeConfig(application_dir=app_dir))
    analysis = AnalysisService(engine_runtime.provider, owns_engine=False)
    continuous = ContinuousAnalysisService(analysis)
    engine_play = EnginePlayService(engine_runtime.provider, owns_engine=False)

    settings = Settings(layout.settings_path)
    language_value = settings.get("language", "uk")
    try:
        language = UILanguage(language_value)
    except (TypeError, ValueError):
        language = UILanguage.UA
    playback = sound_playback
    if playback is None:
        playback = WindowsSoundPlaybackAdapter(
            PackagedSoundAssetResolver(app_dir),
            cache_dir=(layout.root / "sound-cache") if data_root is not None else _sound_cache_dir(),
        )
    sound_runtime = SoundRuntime(
        playback,
        settings=lambda: SoundRuntimeSettings.from_mapping(settings.data),
    )
    game_sounds = GameSoundRuntime(sound_runtime)

    api = Version2ReleaseAccessibleChessAPI(
        continuous_analysis=continuous,
        game_sounds=game_sounds,
        sound_runtime=sound_runtime,
        settings=settings,
        engine_play_service=engine_play,
        lang=language.value,
    )

    database_path = layout.library_path
    application = None

    def build_application() -> Version2Application:
        nonlocal application
        if application is not None:
            raise RuntimeError("Version 2 application is already constructed")
        database = AcsDatabase(database_path)
        try:
            application = Version2Application(
                database,
                progress_store=BookProgressStore(layout.root / "book-progress.json"),
                engine_assistance=EngineAssistedWorkflowService(analysis),
                board_dispatch=api.v2_board_dispatch,
                board_position_projector=api.project_review_fen,
                copy_text=copy_text,
                language=language,
            )
            _share_v2_action_registry(api, application)
            api.bind_version2_application(application)
            return application
        except Exception:
            database.close()
            try:
                continuous.close()
            finally:
                analysis.close()
                engine_runtime.close()
            raise

    if not defer_ui:
        build_application()

    def native_runtime_factory(owner_control: object) -> Version2WindowsFileWorkflowRuntime:
        if owner_control is None:
            raise RuntimeError("Version 2 Windows owner control is unavailable")
        if application is None:
            raise RuntimeError("Version 2 application must be constructed on the native UI first")
        application._assert_thread()
        book_dialogs = _Version2OwnedBookDialogs(lambda: owner_control)
        application.open_book_dialog = book_dialogs.open_book
        file_runtime = Version2WindowsFileWorkflowRuntime(
            owner_control=owner_control,
            get_pgn_session=lambda: application.session,
            set_pgn_session=lambda session: _install_host_confirmed_document(application, session),
            import_services_factory=application.worker_factory(database_path),
            export_selected=application.pgn_commands.export_selected,
            import_ui_ready=application.import_ui_ready,
            pgn_export_event_sink=application._file_event,
            next_delegate=api.v2_board_dispatch,
            current_focus_provider=lambda: str(application._focus),
        )
        file_runtime = _install_close_guard_or_shutdown(
            file_runtime, application, owner_control, book_dialogs
        )
        # Application-owned PGN replacements, including Library -> Open game,
        # reuse the exact owner-bound confirmation source used by native PGN Open.
        # Bind only after the native close guard succeeds so a failed startup
        # cannot leave application state pointing at a retired file runtime.
        application.confirm_document_replace = file_runtime.file_dialogs.confirm_discard_unsaved_pgn
        return file_runtime

    return api, build_application if defer_ui else application, engine_runtime, native_runtime_factory


def main() -> None:
    api, application, runtime, native_runtime_factory = create_version2_release_application(defer_ui=True)
    run_version2_release_window(
        api,
        application,
        runtime,
        file_runtime_factory=native_runtime_factory,
    )


__all__ = ["create_version2_release_application", "main"]
