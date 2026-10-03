from __future__ import annotations

"""Reachability composition for Teacher/Classroom/Education in the one V2 app."""

from collections.abc import Callable, Mapping
from dataclasses import asdict
from pathlib import Path
import sys
from typing import Any

from . import classroom_domain as cd
from .classroom_collaboration import FileQuotaPolicy
from .classroom_collaboration_storage import AttachmentMetadata, ChatMessageMetadata
from .classroom_collaboration_runtime import (
    ClassroomCollaborationRuntime,
    build_classroom_collaboration_http_runtime,
)
from .classroom_collaboration_webview import ClassroomCollaborationWebView
from .classroom_realtime_media import ClassroomMediaController, ClassroomRosterPort
from .education_webview_bridge import EducationWebViewBridge
from .education_webview_projection import EducationWebViewProjection
from .education_workspace import EducationWorkspace
from .education_workspace_store import EducationWorkspaceStore
from .full_product_ui_shell import ROUTES, UILanguage
from .library_export_workspace import build_library_export_webview
from .search_service import GameSearchQuery
from .secret_store import SecretStore, WindowsDpapiSecretStore
from .teacher_webview_bridge import TeacherWebViewBridge
from .teacher_webview_projection import TeacherWebViewProjection
from .teaching_classroom_adapter import apply_classroom_action
from .teaching_session import (
    LessonSession,
    TeachingSessionState,
    start_session,
    validate_lesson_session_scope,
)
from .version2_application import Version2Application
from .version2_final_product_profile import (
    build_final_product_router,
    build_final_product_shell,
    build_final_product_webview_adapter,
)


class Version2FinalProductApplication(Version2Application):
    """One application authority with bounded D09/D10 presentation seams.

    Teacher state remains absent until a trusted host binds an actual canonical
    ``TeachingSessionState`` provider or starts a canonical ``LessonSession``.
    Education state is loaded from the durable D10 workspace store.
    Corrupt/unreadable Education state is never overwritten automatically and
    does not prevent the core chess product from starting.
    """

    def __init__(
        self,
        *args: Any,
        education_workspace_path: str | Path | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        language = self.shell.language

        # Replace only the presentation/router profile. Domain ownership remains
        # in Version2Application and the D09/D10 owners.
        self.shell = build_final_product_shell(language=language)
        self.router = build_final_product_router(self.shell, self._delegate)
        self.adapter = build_final_product_webview_adapter(self.shell, self.router)

        # Library bridge captures the router dispatcher at construction time.
        # Rebuild it so every surface shares the same final registry/router.
        self.library = build_library_export_webview(
            self.database,
            self.router.dispatch,
            language=language,
        )
        self.library.projection.search(GameSearchQuery())

        path = (
            Path(education_workspace_path)
            if education_workspace_path is not None
            else self.progress_store.path.parent / "education-workspace.json"
        )
        self.education_store = EducationWorkspaceStore(path)
        self._education_workspace: EducationWorkspace | None = None
        self._education_revision: str | None = None
        self._education_load_error = False
        self.education: EducationWebViewBridge | None = None
        self._load_education(language)

        self.teacher: TeacherWebViewBridge | None = None
        self._teacher_state_provider: Callable[[], TeachingSessionState] | None = None
        self._teacher_dispatch: Callable[[str, Mapping[str, object]], object] | None = None
        self._teaching_plan: LessonSession | None = None
        self._teaching_state: TeachingSessionState | None = None
        self.collaboration: ClassroomCollaborationWebView | None = None
        self._collaboration_runtime: ClassroomCollaborationRuntime | None = None

    def _load_education(self, language: UILanguage) -> None:
        try:
            loaded = self.education_store.load()
        except Exception:
            self._education_load_error = True
            self._education_workspace = None
            self._education_revision = None
            self.education = None
            return

        if loaded is None:
            self._education_workspace = EducationWorkspace.empty(cd.ClassroomSnapshot())
            self._education_revision = None
        else:
            self._education_workspace = loaded.workspace
            self._education_revision = loaded.revision
        self._education_load_error = False
        self._rebuild_education_bridge(language)

    def _education_provider(self) -> EducationWorkspace:
        workspace = self._education_workspace
        if type(workspace) is not EducationWorkspace:
            raise RuntimeError("Education workspace is unavailable")
        return workspace

    def _education_dispatch(
        self,
        action_id: str,
        payload: Mapping[str, object],
    ) -> object:
        # D10 currently owns canonical records/persistence but no accepted
        # create/open editor workflow is composed into the V2 application yet.
        # Fail closed instead of pretending that a browser mutation succeeded.
        raise RuntimeError(
            f"Education management action is not composed: {action_id}"
        )

    def _rebuild_education_bridge(self, language: UILanguage) -> None:
        if self._education_workspace is None:
            self.education = None
            return
        projection = EducationWebViewProjection(
            self._education_provider,
            self._education_dispatch,
            language=language,
        )
        self.education = EducationWebViewBridge(projection)

    def replace_education_workspace(
        self,
        workspace: EducationWorkspace,
        *,
        expected_revision: str | None,
    ) -> str:
        """Trusted CAS publication seam for a canonical editor owner."""

        self._assert_thread()
        revision = self.education_store.save(
            workspace,
            expected_revision=expected_revision,
        )
        self._education_workspace = workspace
        self._education_revision = revision
        self._education_load_error = False
        self._rebuild_education_bridge(self.shell.language)
        return revision

    @property
    def education_revision(self) -> str | None:
        return self._education_revision

    def _install_teaching_binding(
        self,
        state_provider: Callable[[], TeachingSessionState],
        dispatch: Callable[[str, Mapping[str, object]], object],
    ) -> None:
        """Publish a Teacher bridge only after its canonical projection exists."""

        projection = TeacherWebViewProjection.from_teaching_session(
            dispatch,
            state_provider,
        )
        bridge = TeacherWebViewBridge(
            projection,
            language=self.shell.language,
        )
        self._teacher_state_provider = state_provider
        self._teacher_dispatch = dispatch
        self.teacher = bridge

    def _clear_teaching_binding(self) -> None:
        self.teacher = None
        self._teacher_state_provider = None
        self._teacher_dispatch = None

    def bind_teaching_session(
        self,
        state_provider: Callable[[], TeachingSessionState],
        dispatch: Callable[[str, Mapping[str, object]], object],
    ) -> None:
        """Bind D09 UI directly over an external trusted teaching-session owner."""

        self._assert_thread()
        if self.teacher is not None or self._teaching_state is not None:
            raise RuntimeError("Teaching session is already bound")
        self._install_teaching_binding(state_provider, dispatch)

    def _owned_teaching_state(self) -> TeachingSessionState:
        state = self._teaching_state
        if type(state) is not TeachingSessionState:
            raise RuntimeError("No application-owned teaching session is active")
        return state

    def _dispatch_owned_teaching_action(
        self,
        action_id: str,
        payload: Mapping[str, object],
    ) -> TeachingSessionState:
        """Apply one Teacher action through the canonical D09+D10 CAS boundary."""

        self._assert_thread()
        plan = self._teaching_plan
        state = self._teaching_state
        workspace = self._education_workspace
        if type(plan) is not LessonSession or type(state) is not TeachingSessionState:
            raise RuntimeError("No application-owned teaching session is active")
        if type(workspace) is not EducationWorkspace:
            raise RuntimeError("Education workspace is unavailable")

        next_state = apply_classroom_action(
            plan,
            state,
            workspace.classroom,
            action_id,
            payload,
            expected_revision=state.revision,
        )
        self._teaching_state = next_state
        return next_state

    def start_teaching_session(self, plan: LessonSession) -> TeachingSessionState:
        """Start one trusted canonical D09 lesson against current durable D10 scope.

        The browser cannot supply or replace the plan. Validation and canonical
        state construction complete before the Teacher surface becomes reachable.
        Any projection/binding failure rolls the in-memory session back entirely.
        """

        self._assert_thread()
        if type(plan) is not LessonSession:
            raise TypeError("teaching plan must be LessonSession")
        if self.teacher is not None or self._teaching_state is not None:
            raise RuntimeError("Teaching session is already bound")
        workspace = self._education_workspace
        if type(workspace) is not EducationWorkspace:
            raise RuntimeError("Education workspace is unavailable")

        validate_lesson_session_scope(plan, workspace.classroom)
        state = start_session(plan)
        self._teaching_plan = plan
        self._teaching_state = state
        try:
            self._install_teaching_binding(
                self._owned_teaching_state,
                self._dispatch_owned_teaching_action,
            )
        except Exception:
            self._teaching_plan = None
            self._teaching_state = None
            self._clear_teaching_binding()
            raise
        return state

    def stop_teaching_session(self) -> None:
        """Retire the application-owned live lesson and remove its Teacher bridge."""

        self._assert_thread()
        if self._teaching_state is None:
            raise RuntimeError("No application-owned teaching session is active")
        self._teaching_plan = None
        self._teaching_state = None
        self._clear_teaching_binding()

    def unbind_teaching_session(self) -> None:
        """Unbind any trusted Teacher owner and discard only local live ownership."""

        self._assert_thread()
        self._teaching_plan = None
        self._teaching_state = None
        self._clear_teaching_binding()

    def bind_classroom_collaboration(
        self,
        collaboration: ClassroomCollaborationWebView,
        *,
        file_progress_event_sink: Callable[[dict[str, object]], object] | None = None,
    ) -> None:
        """Bind #29 UI and its optional trusted host-to-browser progress seam."""

        self._assert_thread()
        if not isinstance(collaboration, ClassroomCollaborationWebView):
            raise TypeError("collaboration must be ClassroomCollaborationWebView")
        if file_progress_event_sink is not None and not callable(file_progress_event_sink):
            raise TypeError("file_progress_event_sink must be callable")
        if self.collaboration is not None:
            raise RuntimeError("Classroom collaboration is already bound")
        collaboration.set_language(self.shell.language)
        # Binding owns the trusted host observer. Explicitly clear any observer
        # left on a WebView assembled by another host instead of inheriting it.
        collaboration.set_file_progress_event_sink(
            None
            if file_progress_event_sink is None
            else lambda event: file_progress_event_sink(asdict(event))
        )
        self.collaboration = collaboration

    def configure_classroom_collaboration_http(
        self,
        *,
        room_id: str,
        participant_id: str,
        roster: ClassroomRosterPort,
        chat_endpoint_url: str,
        file_endpoint_url: str,
        chat_bearer_token_provider: Callable[[], str],
        file_bearer_token_provider: Callable[[], str],
        participant_label: Callable[[str], str],
        collaboration_store_path: str | Path | None = None,
        chat_secret_store: SecretStore | None = None,
        file_picker: Callable[[], Path | None] | None = None,
        file_saver: Callable[[str, str], object] | None = None,
        file_opener: Callable[[str, str], object] | None = None,
        file_progress_event_sink: Callable[[dict[str, object]], object] | None = None,
        moderation_allowed: Callable[[], bool] | None = None,
        participant_moderation: ClassroomMediaController | None = None,
        chat_retention: str = "session",
        file_retention: str = "session",
        local_quota: FileQuotaPolicy | None = None,
        chat_timeout_seconds: float = 15.0,
        file_timeout_seconds: float = 30.0,
        allow_insecure_loopback: bool = False,
    ) -> ClassroomCollaborationRuntime:
        """Compose and bind the approved authenticated Issue #29 HTTP runtime."""

        self._assert_thread()
        if self.collaboration is not None or getattr(
            self, "_collaboration_runtime", None
        ) is not None:
            raise RuntimeError("Classroom collaboration is already bound")
        if file_progress_event_sink is not None and not callable(
            file_progress_event_sink
        ):
            raise TypeError("file_progress_event_sink must be callable")

        if collaboration_store_path is None:
            path = self.progress_store.path.parent / "classroom-collaboration.sqlite3"
        elif isinstance(collaboration_store_path, Path):
            path = collaboration_store_path
        elif type(collaboration_store_path) is str and collaboration_store_path:
            path = Path(collaboration_store_path)
        else:
            raise TypeError(
                "collaboration_store_path must be a non-empty path"
            )
        effective_chat_secret_store = chat_secret_store
        if effective_chat_secret_store is None and sys.platform == "win32":
            # The shipping Windows product has an approved current-user DPAPI
            # authority. Keep encrypted outbox material beside other per-user
            # application state without reading ambient provider credentials.
            effective_chat_secret_store = WindowsDpapiSecretStore(
                path.parent / "secure"
            )
        runtime = build_classroom_collaboration_http_runtime(
            room_id=room_id,
            participant_id=participant_id,
            roster=roster,
            store_path=path,
            chat_endpoint_url=chat_endpoint_url,
            file_endpoint_url=file_endpoint_url,
            chat_bearer_token_provider=chat_bearer_token_provider,
            file_bearer_token_provider=file_bearer_token_provider,
            participant_label=participant_label,
            language=self.shell.language,
            chat_secret_store=effective_chat_secret_store,
            file_picker=file_picker,
            file_saver=file_saver,
            file_opener=file_opener,
            moderation_allowed=moderation_allowed,
            participant_moderation=participant_moderation,
            chat_retention=chat_retention,
            file_retention=file_retention,
            local_quota=local_quota,
            chat_timeout_seconds=chat_timeout_seconds,
            file_timeout_seconds=file_timeout_seconds,
            allow_insecure_loopback=allow_insecure_loopback,
        )
        self.bind_classroom_collaboration(
            runtime.webview,
            file_progress_event_sink=file_progress_event_sink,
        )
        self._collaboration_runtime = runtime
        return runtime

    def unbind_classroom_collaboration(self) -> None:
        """Remove the presentation binding without mutating durable collaboration data."""

        self._assert_thread()
        collaboration = self.collaboration
        if collaboration is not None:
            collaboration.retire_browser_session()
        self.collaboration = None
        self._collaboration_runtime = None

    def receive_classroom_chat(
        self,
        message: ChatMessageMetadata,
    ) -> dict[str, object]:
        """Accept one trusted live chat delivery through the bound collaboration core."""

        self._assert_thread()
        collaboration = self.collaboration
        if collaboration is None:
            raise RuntimeError("Classroom collaboration is not bound")
        return asdict(collaboration.receive_chat(message))

    def receive_classroom_file(
        self,
        attachment: AttachmentMetadata,
    ) -> dict[str, object]:
        """Accept one trusted live file delivery through the bound collaboration core."""

        self._assert_thread()
        collaboration = self.collaboration
        if collaboration is None:
            raise RuntimeError("Classroom collaboration is not bound")
        return asdict(collaboration.receive_file(attachment))

    def refresh_classroom_chat(self) -> dict[str, object]:
        """Run canonical chat sync after a trusted provider notification."""

        self._assert_thread()
        collaboration = self.collaboration
        if collaboration is None:
            raise RuntimeError("Classroom collaboration is not bound")
        return asdict(collaboration.refresh_chat())

    def refresh_classroom_files(self) -> dict[str, object]:
        """Run canonical file/state sync after a trusted provider notification."""

        self._assert_thread()
        collaboration = self.collaboration
        if collaboration is None:
            raise RuntimeError("Classroom collaboration is not bound")
        return asdict(collaboration.refresh_files())

    def sync_composed_surfaces_language(self, language: UILanguage) -> None:
        self._assert_thread()
        if not isinstance(language, UILanguage):
            raise TypeError("full-product language must be UILanguage")
        self._rebuild_education_bridge(language)
        if self.collaboration is not None:
            self.collaboration.set_language(language)
        if self._teacher_state_provider is not None and self._teacher_dispatch is not None:
            projection = TeacherWebViewProjection.from_teaching_session(
                self._teacher_dispatch,
                self._teacher_state_provider,
            )
            self.teacher = TeacherWebViewBridge(projection, language=language)

    def browser_command(
        self,
        area: str,
        command: str,
        payload: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        self._assert_thread()
        if area == "teacher":
            if self.teacher is None:
                return self._error()
            return asdict(self.teacher.dispatch(command, payload))
        if area in {"classes", "education"}:
            if type(command) is str and command.startswith("collaboration."):
                if self.collaboration is None:
                    return self._error()
                return asdict(self.collaboration.dispatch(command, payload))
            if self.education is None:
                return self._error()
            return asdict(self.education.dispatch(command, payload))
        return super().browser_command(area, command, payload)

    def _education_browser_snapshot(self) -> dict[str, object] | None:
        if self.education is None:
            if self.collaboration is None:
                return None
            classes_heading = next(
                route.label(self.shell.language)
                for route in ROUTES
                if route.route_id == "classes"
            )
            return {
                "document": {
                    "lang": self.shell.language.value,
                    "heading": classes_heading,
                },
                "sections": (),
                "detail": None,
                "collaboration": self.collaboration.safe_snapshot(),
            }
        snapshot = dict(self.education.projection.snapshot())
        if self.collaboration is not None:
            snapshot["collaboration"] = self.collaboration.safe_snapshot()
        return snapshot

    def snapshot(self) -> dict[str, object]:
        self._assert_thread()
        result = super().snapshot()
        result.update(
            {
                "teacher": (
                    None
                    if self.teacher is None
                    else self.teacher.projection.snapshot(
                        language=self.shell.language.value
                    )
                ),
                "education": self._education_browser_snapshot(),
                "product_status": {
                    "teacher_session_active": self.teacher is not None,
                    "education_available": self.education is not None,
                    "education_recovery_required": self._education_load_error,
                    "collaboration_available": self.collaboration is not None,
                    "remote_transport": (
                        "classroom_collaboration_http"
                        if getattr(self, "_collaboration_runtime", None) is not None
                        else "not_approved"
                    ),
                },
            }
        )
        return result
