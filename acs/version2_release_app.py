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

from . import __version__ as _product_version
from .acsdb import AcsDatabase
from .analysis_service import AnalysisService
from .book_progress_store import BookProgressStore
from .continuous_analysis import ContinuousAnalysisService
from .child_coaching_application import ChildCoachingApplication
from .child_coaching_rotation_store import ChildCoachingRotationStore
from .child_coaching_store import ChildCoachingTemplateStore
from .engine_assisted_workflows import EngineAssistedWorkflowService
from .engine_play_service import EnginePlayService
from .full_product_ui_shell import UILanguage
from .local_profile import LocalProfileStore
from .release_app import _sound_cache_dir, _sound_variant_provider, _user_root
from .protection_boundary import (
    ADVANCED_SECURITY_RUNTIME_API_VERSION,
    ENTITLEMENT_RUNTIME_API_VERSION,
    ProtectedStartupLocked,
    ProtectionDecision,
    ProtectionStartupSession,
    open_release_protection_session,
)
from .protection_locked_ui import run_locked_security_window
from .protection_entitlement_lifecycle import ProtectionEntitlementLifecycle
from .protection_advanced_boundary import (
    ProtectionAdvancedError,
    ProtectionCapabilityGate,
    ProtectionTrustBoundary,
    ProtectionTrustedTimeSource,
    ProtectionUpdateChannel,
    ProtectionUpdateInstaller,
    ProtectionUpdateSignatureVerifier,
)
from .release_update_center import ReleaseUpdateCenter
from .settings import Settings
from .sound_runtime import GameSoundRuntime, SoundRuntime, SoundRuntimeSettings
from .sound_windows import PackagedSoundAssetResolver, WindowsSoundPlaybackAdapter
from .stockfish_runtime import StockfishRuntime, StockfishRuntimeConfig
from .student_progress_store import StudentProgressStore
from .v1_runtime_bridge import V1RuntimeBridgeCoordinator
from .version2_application import Version2Application
from .version2_final_product_application import Version2FinalProductApplication

# Mutable release composition seam.  The direct release root defaults to the
# complete Teacher/Education-capable application, while stacked packaged release
# wrappers may temporarily replace Version2Application with richer subclasses.
Version2Application = Version2FinalProductApplication
from .version2_gametree_resume import Version2GameTreeResumeCoordinator
from .version2_local_profile_api import Version2ProfileAccessibleChessAPI
from .version2_release_ui import Version2ReleaseAccessibleChessAPI, run_version2_release_window
from .version2_upgrade import UserDataLayout, Version2UpgradeCoordinator
from .user_data_portability import BundleKind
from .version2_user_data_portability_host import (
    Version2UserDataPortabilityHost,
    begin_pending_user_data_operation,
)
from .version2_windows_host_runtime import Version2WindowsFileWorkflowRuntime
from .version2_windows_import_ui_pump import Version2WinFormsUiPoster
from .version2_windows_book_open_worker import Version2BookOpenWorker
from .version2_windows_native_dialog_ownership import Version2OwnedWindowsFileDialogs
from .webapp_keymap import _asset_root


class _Version2OwnedBookDialogs(Version2OwnedWindowsFileDialogs):
    """Owner-bound Open and release-lifecycle dialogs for supported books/PGN."""

    def open_book(self) -> Path | None:
        DialogResult, OpenFileDialog, _ = self._load_forms()
        dialog = OpenFileDialog()
        try:
            dialog.Title = self.dialog_text("open_book_title")
            dialog.Filter = self.dialog_text("book_filter")
            dialog.CheckFileExists = True
            dialog.CheckPathExists = True
            dialog.Multiselect = False
            return self._selected(dialog, dialog.ShowDialog(), DialogResult.OK)
        finally:
            dialog.Dispose()

    def confirm_recover_book_progress(self) -> bool:
        """Confirm rollback to the previous valid Book-progress snapshot."""

        owner = self._dialog_owner.resolve()
        DialogResult, _, _ = self._forms_loader()
        MessageBox, MessageBoxButtons, MessageBoxIcon = self._message_box_loader()
        result = MessageBox.Show(
            owner,
            self.dialog_text("book_progress_recovery_message"),
            self.dialog_text("book_progress_recovery_title"),
            MessageBoxButtons.YesNo,
            MessageBoxIcon.Warning,
        )
        return result == DialogResult.Yes

    def confirm_discard_unsaved_pgn_on_exit(self) -> bool:
        """Confirm destructive application close on the exact native owner Form."""

        owner = self._dialog_owner.resolve()
        DialogResult, _, _ = self._forms_loader()
        MessageBox, MessageBoxButtons, MessageBoxIcon = self._message_box_loader()
        result = MessageBox.Show(
            owner,
            self.dialog_text("exit_unsaved_pgn_message"),
            self.dialog_text("exit_unsaved_pgn_title"),
            MessageBoxButtons.YesNo,
            MessageBoxIcon.Warning,
        )
        return result == DialogResult.Yes


class _Version2OwnedUserDataArchiveDialogs(_Version2OwnedBookDialogs):
    """Owner-bound native archive chooser; browser payloads never carry paths."""

    @staticmethod
    def _archive_filter() -> str:
        return "Accessible Chess data (*.acdata)|*.acdata|All files (*.*)|*.*"

    def save_archive(self, kind: BundleKind) -> Path | None:
        DialogResult, _, SaveFileDialog = self._load_forms()
        dialog = SaveFileDialog()
        try:
            dialog.Title = (
                "Back up Accessible Chess user data"
                if kind is BundleKind.BACKUP
                else "Export Accessible Chess user data"
            )
            dialog.Filter = self._archive_filter()
            dialog.DefaultExt = "acdata"
            dialog.AddExtension = True
            dialog.OverwritePrompt = True
            return self._selected(dialog, dialog.ShowDialog(), DialogResult.OK)
        finally:
            dialog.Dispose()

    def open_archive(self, kind: BundleKind) -> Path | None:
        DialogResult, OpenFileDialog, _ = self._load_forms()
        dialog = OpenFileDialog()
        try:
            dialog.Title = (
                "Restore Accessible Chess user data"
                if kind is BundleKind.BACKUP
                else "Import Accessible Chess user data"
            )
            dialog.Filter = self._archive_filter()
            dialog.CheckFileExists = True
            dialog.CheckPathExists = True
            dialog.Multiselect = False
            return self._selected(dialog, dialog.ShowDialog(), DialogResult.OK)
        finally:
            dialog.Dispose()


def _install_unsaved_pgn_close_guard(
    application: Version2Application,
    owner_control: object,
    dialogs: object,
    *,
    before_shutdown: Callable[[Version2Application], Any] | None = None,
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
    if before_shutdown is not None and not callable(before_shutdown):
        raise TypeError("Version 2 pre-shutdown hook must be callable or None")
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
        except BaseException as error:
            raise RuntimeError("Version 2 native close cannot be cancelled") from error

    def announce_close_failure() -> None:
        reporter = getattr(application, "announce_shutdown_failure", None)
        if not callable(reporter):
            return
        try:
            reporter()
        except BaseException:
            # Presentation is secondary to preserving the live owner and the
            # original shutdown/resume failure that made FormClosing refuse.
            pass

    def clear_close_failure_diagnostics() -> None:
        # Each accepted close attempt owns fresh diagnostic truth. Historical
        # failure objects must not survive a later successful retry or mask an
        # incomplete-but-nonexceptional shutdown.
        for name in ("_native_close_resume_error", "_native_close_shutdown_error"):
            try:
                setattr(application, name, None)
            except BaseException:
                # Diagnostics are secondary to the close transaction itself.
                pass

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
            except BaseException:
                dirty = True

            if dirty:
                try:
                    discard = confirmation() is True
                except BaseException:
                    announce_close_failure()
                    cancel_close(event)
                    return
                if not discard:
                    cancel_close(event)
                    return

            clear_close_failure_diagnostics()

            if before_shutdown is not None:
                try:
                    before_shutdown(application)
                except BaseException as error:
                    setattr(application, "_native_close_resume_error", error)
                    announce_close_failure()
                    cancel_close(event)
                    return

            try:
                shutdown_complete = shutdown() is True
            except BaseException as error:
                setattr(application, "_native_close_shutdown_error", error)
                announce_close_failure()
                cancel_close(event)
                return
            if not shutdown_complete:
                announce_close_failure()
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
    *,
    before_shutdown: Callable[[Version2Application], Any] | None = None,
):
    """Install the close guard or synchronously retire the unbound runtime.

    The native file runtime is allocated before it can be bound to the application.
    If FormClosing/owner/dialog validation fails at that boundary, the outer release
    cleanup cannot see that runtime.  Close it here before propagating the original
    guard failure; never leave a worker/pump ownerless during startup.
    """

    try:
        _install_unsaved_pgn_close_guard(
            application,
            owner_control,
            dialogs,
            before_shutdown=before_shutdown,
        )
    except BaseException:
        # The close-guard failure is the startup authority. Cleanup is best
        # effort here; native_runtime_factory performs a second idempotent
        # retirement attempt before propagating the same primary failure.
        try:
            shutdown_runtime = getattr(file_runtime, "shutdown", None)
            if callable(shutdown_runtime):
                shutdown_runtime()
        except BaseException:
            pass
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

    Production ``KeymapService`` re-adopts the persisted profile against the
    wider V2/Product definition set before it points at that exact registry.
    This preserves Product-only remaps across restart (including valid binding
    swaps that cannot be replayed incrementally) while keeping keyboard
    resolution, WebView commands and the native Windows menu on one authority.
    """

    registry = application.adapter.registry
    adopt = getattr(api.keymap_service, "adopt_registry", None)
    if callable(adopt):
        return adopt(registry)

    # Compatibility for narrow test doubles/embedders that expose the historical
    # editor-only service shape. Production KeymapService always takes the
    # validated adopt_registry path above.
    source = api.keymap_service.editor.registry
    profile = source.to_profile()
    bindings = profile.get("bindings", {})
    aliases = profile.get("aliases", {})
    if not isinstance(bindings, Mapping) or not isinstance(aliases, Mapping):
        raise ValueError("stored keymap profile is invalid")
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
    application_dir: str | Path | None = None,
    coordinator_factory: Callable[[UserDataLayout], Any] = Version2UpgradeCoordinator,
    bridge_factory: Callable[[UserDataLayout, Path], Any] = V1RuntimeBridgeCoordinator,
) -> UserDataLayout:
    """Recover/upgrade user data before any normal settings or database writer opens.

    A shipped V1 installation stored its user data beside ``AccessibleChess.exe``.
    When that exact packaged executable exists, import that bounded legacy topology
    first.  Then run the canonical in-root V2 upgrader.  Source/diagnostic trees with
    no packaged executable retain the existing V2-only startup path.
    """

    if not callable(coordinator_factory):
        raise TypeError("coordinator_factory must be callable")
    if not callable(bridge_factory):
        raise TypeError("bridge_factory must be callable")
    layout = _version2_user_data_layout(data_root=data_root, settings_path=settings_path)
    # Section 37 restore/import is published before normal Settings/SQLite writers
    # open, but remains rollback-capable until the canonical upgrader validates it.
    portability_transaction = begin_pending_user_data_operation(layout)
    try:
        if application_dir is not None:
            executable = Path(application_dir) / "AccessibleChess.exe"
            if executable.is_file():
                bridge = bridge_factory(layout, executable)
                bridge_run = getattr(bridge, "run", None)
                if not callable(bridge_run):
                    raise TypeError("V1 runtime bridge coordinator must expose run()")
                bridge_run()

        coordinator = coordinator_factory(layout)
        run = getattr(coordinator, "run", None)
        if not callable(run):
            raise TypeError("Version 2 upgrade coordinator must expose run()")
        run()
    except BaseException:
        if portability_transaction is not None:
            portability_transaction.rollback()
        raise
    else:
        if portability_transaction is not None:
            portability_transaction.commit()
    return layout


def _close_partial_version2_composition(*resources: Any | None) -> None:
    """Best-effort unwind for resources acquired before V2 composition completes.

    The constructor/startup exception is the primary failure. Cleanup therefore
    runs in caller-supplied reverse ownership order, attempts every acquired
    resource, and never replaces the primary exception with a close failure.
    """

    for resource in resources:
        if resource is None:
            continue
        close = getattr(resource, "close", None)
        if not callable(close):
            continue
        try:
            close()
        except BaseException:
            pass


def create_version2_release_application(
    *,
    application_dir: str | Path | None = None,
    runtime_factory: Callable[[StockfishRuntimeConfig], Any] = StockfishRuntime,
    sound_playback: Any | None = None,
    settings_path: str | Path | None = None,
    data_root: str | Path | None = None,
    copy_text: Callable[[str], Any] = _copy_text_to_windows_clipboard,
    defer_ui: bool = False,
    protection_authorizer: Callable[..., Any] = open_release_protection_session,
):
    """Compose one engine provider plus the persistent V2 application state.

    Persistent state is recovered/upgraded before any normal ``Settings`` or
    ``AcsDatabase`` writer opens.  The returned native-runtime factory must then be
    called on the actual Windows UI thread with the exact pywebview owner control.
    With ``defer_ui=True`` the second return value is a one-shot application
    factory, invoked by the window's synchronous before_show event on its native
    STA thread. Diagnostics can keep the eager, calling-thread composition.
    """

    app_dir = Path(application_dir) if application_dir is not None else _asset_root()
    if not callable(protection_authorizer):
        raise TypeError("protection_authorizer must be callable")
    protection_state_root = Path(data_root) if data_root is not None else _user_root()
    # R00-R14 protection is evaluated before any premium engine/database/application
    # resource is constructed. A locked packaged release therefore cannot reach
    # Stockfish, Library, Books, Training or other premium composition by accident.
    protection_result = protection_authorizer(
        application_dir=app_dir,
        state_root=protection_state_root,
    )
    protection_session: ProtectionStartupSession | None = None
    if isinstance(protection_result, ProtectionStartupSession):
        if not protection_result.decision.authorized:
            raise RuntimeError("authorized startup session contains a locked decision")
        protection_session = protection_result
    elif protection_result is not None and not isinstance(protection_result, ProtectionDecision):
        # Test/integration seams may intentionally return None. Any other
        # unexpected authority object is rejected instead of silently ignored.
        raise TypeError("protection authorizer returned an unsupported result")

    capability_gate: ProtectionCapabilityGate | None = None
    release_update_center: ReleaseUpdateCenter | None = None
    if (
        protection_session is not None
        and protection_session.decision.build_id != "source-development"
    ):
        try:
            runtime_version = protection_session.client.runtime_api_version()
            if runtime_version >= ENTITLEMENT_RUNTIME_API_VERSION:
                lifecycle = ProtectionEntitlementLifecycle(
                    protection_session.client
                ).synchronize()
                if not lifecycle.premium_allowed:
                    raise ProtectedStartupLocked(
                        ProtectionDecision(
                            state="locked",
                            reason=lifecycle.reason,
                            safe_operations=protection_session.decision.safe_operations,
                            capabilities=frozenset(),
                            build_id=protection_session.decision.build_id,
                        ),
                        protection_session.client,
                    )
            if runtime_version >= ADVANCED_SECURITY_RUNTIME_API_VERSION:
                trust = ProtectionTrustBoundary(protection_session.client).synchronize()
                if trust.state != "trusted":
                    raise ProtectedStartupLocked(
                        ProtectionDecision(
                            state="locked",
                            reason=trust.reason,
                            safe_operations=protection_session.decision.safe_operations,
                            capabilities=frozenset(),
                            build_id=protection_session.decision.build_id,
                        ),
                        protection_session.client,
                    )
                capability_gate = ProtectionCapabilityGate(protection_session.client)
                capability_gate.require_surface("licensing.local")
                capability_gate.require_surface("persistence.local")
                capability_gate.require_surface("integration.local")
                release_update_center = ReleaseUpdateCenter(
                    current_version=_product_version.split("-", 1)[0],
                    channel=ProtectionUpdateChannel(protection_session.client),
                    verifier=ProtectionUpdateSignatureVerifier(protection_session.client),
                    time_source=ProtectionTrustedTimeSource(protection_session.client),
                    installer=ProtectionUpdateInstaller(protection_session.client),
                )
        except ProtectedStartupLocked:
            raise
        except Exception:
            raise ProtectedStartupLocked(
                ProtectionDecision(
                    state="locked",
                    reason="advanced_security_unavailable",
                    safe_operations=protection_session.decision.safe_operations,
                    capabilities=frozenset(),
                    build_id=protection_session.decision.build_id,
                ),
                protection_session.client,
            ) from None

    layout = _prepare_version2_user_data(
        data_root=data_root,
        settings_path=settings_path,
        application_dir=app_dir,
    )
    resume_coordinator = Version2GameTreeResumeCoordinator(
        layout.root / "gametree-resume.json"
    )

    engine_runtime: Any | None = None
    analysis: Any | None = None
    continuous: Any | None = None
    try:
        if capability_gate is not None:
            capability_gate.require_surface("engine.local")
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
        sound_assets = PackagedSoundAssetResolver(app_dir)
        selected_sound_variant = _sound_variant_provider(settings, sound_assets)

        playback = sound_playback
        if playback is None:
            playback = WindowsSoundPlaybackAdapter(
                sound_assets,
                cache_dir=(layout.root / "sound-cache") if data_root is not None else _sound_cache_dir(),
                variant_provider=selected_sound_variant,
            )
        sound_runtime = SoundRuntime(
            playback,
            settings=lambda: SoundRuntimeSettings.from_mapping(settings.data),
        )
        game_sounds = GameSoundRuntime(sound_runtime)

        if capability_gate is not None:
            capability_gate.require_surface("chess.local")
        api = Version2ProfileAccessibleChessAPI(
            continuous_analysis=continuous,
            profile_store=LocalProfileStore(layout.root / "profile.json"),
            game_sounds=game_sounds,
            sound_runtime=sound_runtime,
            settings=settings,
            sound_asset_resolver=sound_assets,
            engine_play_service=engine_play,
            lang=language.value,
        )
        # Host-only security state. It is never returned through the pywebview
        # public method surface; the release host consumes it for periodic R26 checks.
        api._protection_session = protection_session
        api._protection_capability_gate = capability_gate
    except BaseException:
        _close_partial_version2_composition(continuous, analysis, engine_runtime)
        raise

    database_path = layout.library_path
    application = None
    application_build_failed = False

    def build_application() -> Version2Application:
        nonlocal application, application_build_failed
        if application is not None:
            raise RuntimeError("Version 2 application is already constructed")
        if application_build_failed:
            raise RuntimeError("Version 2 application construction previously failed")
        database: Any | None = None
        try:
            if capability_gate is not None:
                capability_gate.require_surface("library.local")
                capability_gate.require_surface("books.training")
            database = AcsDatabase(database_path)
            candidate = Version2Application(
                database,
                progress_store=BookProgressStore(layout.root / "book-progress.json"),
                engine_assistance=EngineAssistedWorkflowService(analysis),
                board_dispatch=api.v2_board_dispatch,
                board_position_projector=api.project_review_fen,
                copy_text=copy_text,
                language=language,
                release_update_center=release_update_center,
                security_action_guard=(
                    capability_gate.require_action
                    if capability_gate is not None
                    else None
                ),
            )
            progress_binder = getattr(candidate, "bind_student_progress_store", None)
            if callable(progress_binder):
                if capability_gate is not None:
                    capability_gate.require_surface("classroom.local")
                progress_binder(
                    StudentProgressStore(layout.root / "student-progress.json")
                )
            child_coaching_binder = getattr(
                candidate,
                "bind_child_coaching_application",
                None,
            )
            if callable(child_coaching_binder):
                child_coaching_binder(
                    ChildCoachingApplication(
                        ChildCoachingTemplateStore(
                            layout.root / "child-coaching.json"
                        )
                    )
                )
            rotation_binder = getattr(
                candidate,
                "bind_child_coaching_rotation_store",
                None,
            )
            if callable(rotation_binder):
                rotation_binder(
                    ChildCoachingRotationStore(
                        layout.root / "child-coaching-rotation.json"
                    )
                )
            resume_coordinator.restore(candidate)
            _share_v2_action_registry(api, candidate)
            api.bind_version2_application(candidate)
            application = candidate
            return candidate
        except BaseException:
            application_build_failed = True
            _close_partial_version2_composition(
                database,
                continuous,
                analysis,
                engine_runtime,
            )
            raise

    if not defer_ui:
        build_application()

    def native_runtime_factory(owner_control: object) -> Version2WindowsFileWorkflowRuntime:
        if capability_gate is not None:
            capability_gate.require_surface("formats.core")
        if owner_control is None:
            raise RuntimeError("Version 2 Windows owner control is unavailable")
        if application is None:
            raise RuntimeError("Version 2 application must be constructed on the native UI first")
        application._assert_thread()
        dialog_language_provider = lambda: application.shell.language
        book_dialogs = _Version2OwnedBookDialogs(
            lambda: owner_control,
            language_provider=dialog_language_provider,
        )
        portability_dialogs = _Version2OwnedUserDataArchiveDialogs(
            lambda: owner_control,
            language_provider=dialog_language_provider,
        )
        portability_host = Version2UserDataPortabilityHost(
            layout,
            save_dialog=portability_dialogs.save_archive,
            open_dialog=portability_dialogs.open_archive,
        )
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
            dialog_language_provider=dialog_language_provider,
        )
        book_open_worker = None
        try:
            # File runtime ownership already exists at this point. Keep Book
            # worker/poster construction inside the same unwind boundary so a
            # constructor abort cannot orphan the file worker/pump.
            book_open_worker = Version2BookOpenWorker(
                prepare=application.prepare_book_open,
                commit=application.commit_prepared_book_open,
                post_to_ui=Version2WinFormsUiPoster(owner_control),
                event_sink=application._book_open_event,
            )
            application.bind_book_open_worker(book_open_worker)
            file_runtime = _install_close_guard_or_shutdown(
                file_runtime,
                application,
                owner_control,
                book_dialogs,
                before_shutdown=resume_coordinator.prepare_shutdown,
            )
            # Publish Section-37 filesystem authority only after the real native
            # owner and shutdown guard are live. Browser/model code gets no path.
            application.bind_user_data_portability(portability_host)
        except BaseException:
            # Startup publication failed before the native runtime became a
            # usable product owner. Retire every newly acquired native worker,
            # release only this unpublished Book-worker binding, and preserve
            # the original startup failure even if cleanup itself aborts.
            if book_open_worker is not None:
                try:
                    book_open_worker.shutdown()
                except BaseException:
                    pass
                try:
                    application.unbind_book_open_worker(book_open_worker)
                except BaseException:
                    pass
            try:
                file_runtime.shutdown()
            except BaseException:
                pass
            raise
        # Publish every owner-bound application callback only after the native
        # runtime and FormClosing guard are both live. Failed startup must leave
        # no callback pointing at a retired/unowned Form.
        application.open_book_dialog = book_dialogs.open_book
        application.confirm_book_progress_recovery = book_dialogs.confirm_recover_book_progress
        application.confirm_document_replace = file_runtime.file_dialogs.confirm_discard_unsaved_pgn
        return file_runtime

    return api, build_application if defer_ui else application, engine_runtime, native_runtime_factory


def main() -> None:
    try:
        api, application, runtime, native_runtime_factory = create_version2_release_application(
            defer_ui=True
        )
    except ProtectedStartupLocked as locked:
        # The locked shell is the only user-facing surface before authorization.
        # It can create/import the signed offline entitlement through the private
        # runtime boundary, then retry. Premium composition is attempted only after
        # the private runtime returns an authorized decision.
        if not run_locked_security_window(locked.client, locked.decision):
            return
        api, application, runtime, native_runtime_factory = create_version2_release_application(
            defer_ui=True
        )

    run_version2_release_window(
        api,
        application,
        runtime,
        file_runtime_factory=native_runtime_factory,
    )


__all__ = ["create_version2_release_application", "main"]
