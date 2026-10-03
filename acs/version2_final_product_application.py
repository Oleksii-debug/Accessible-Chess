from __future__ import annotations

"""Reachability composition for Teacher/Classroom/Education in the one V2 app."""

from collections.abc import Callable, Mapping
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from . import classroom_domain as cd
from .classroom_media_provider_binder import ClassroomMediaProviderBinder
from .classroom_media_webview_bridge import ClassroomMediaWebViewBridge
from .classroom_media_webview_projection import (
    ClassroomMediaWebViewProjection,
    ParticipantLabelsProvider,
)
from .classroom_media_webview_transactions import (
    ClassroomMediaBrowserProviderConfig,
    ClassroomMediaTransactionalWebView,
)
from .classroom_realtime_media import ClassroomMediaController, JoinCredential
from .education_webview_bridge import EducationWebViewBridge
from .education_webview_projection import EducationWebViewProjection
from .education_workspace import EducationWorkspace
from .education_workspace_store import EducationWorkspaceStore
from .full_product_ui_shell import UILanguage
from .library_export_workspace import build_library_export_webview
from .search_service import GameSearchQuery
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
        self.media: ClassroomMediaWebViewBridge | None = None
        self.media_transactions: ClassroomMediaTransactionalWebView | None = None
        self._teacher_state_provider: Callable[[], TeachingSessionState] | None = None
        self._teacher_dispatch: Callable[[str, Mapping[str, object]], object] | None = None
        self._teaching_plan: LessonSession | None = None
        self._teaching_state: TeachingSessionState | None = None

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

    def bind_classroom_media(
        self,
        controller: ClassroomMediaController,
        participant_labels_provider: ParticipantLabelsProvider,
        *,
        provider_binder: ClassroomMediaProviderBinder | None = None,
        provider_config: ClassroomMediaBrowserProviderConfig | None = None,
    ) -> None:
        """Bind browser media to one canonical owner, optionally transactionally."""

        self._assert_thread()
        if self.media is not None:
            raise RuntimeError("Classroom media is already bound")
        if (provider_binder is None) != (provider_config is None):
            raise ValueError(
                "classroom media transactional binding requires binder and provider config"
            )
        projection = ClassroomMediaWebViewProjection(
            controller,
            participant_labels_provider,
            language=self.shell.language,
        )
        # Force one complete safe projection before publishing browser reachability.
        projection.snapshot()

        transactions: ClassroomMediaTransactionalWebView | None = None
        bridge: ClassroomMediaWebViewBridge
        if provider_binder is None:
            bridge = ClassroomMediaWebViewBridge(projection)
        else:
            transactions = ClassroomMediaTransactionalWebView(
                projection,
                provider_binder,
                provider_config,
            )
            bridge = ClassroomMediaWebViewBridge(
                projection,
                mutations=transactions,
            )

        self.media_transactions = transactions
        self.media = bridge

    def unbind_classroom_media(self) -> None:
        """Remove only a quiescent presentation binding; provider teardown stays owned."""

        self._assert_thread()
        transactions = self.media_transactions
        if transactions is not None and (
            transactions.binder.active_lease is not None
            or transactions.binder.recovery_status is not None
        ):
            raise RuntimeError(
                "Classroom media cannot be unbound while provider recovery is active"
            )
        if (
            transactions is not None
            and transactions.projection.controller.state.connected
        ):
            raise RuntimeError(
                "Classroom media cannot be unbound while provider session is connected"
            )
        self.media = None
        self.media_transactions = None

    def prepare_classroom_media_join(
        self,
        credential: JoinCredential,
        *,
        now: datetime,
    ) -> dict[str, object]:
        """Trusted host entrypoint; enqueue one secret-safe provider join dispatch."""

        self._assert_thread()
        transactions = self.media_transactions
        if transactions is None:
            raise RuntimeError("Transactional classroom media is not bound")
        event = transactions.prepare_join(credential, now=now)
        rendered = asdict(event)
        self._events.append(rendered)
        return rendered

    def prepare_classroom_media_reconnect(
        self,
        credential: JoinCredential,
        *,
        now: datetime,
    ) -> dict[str, object]:
        """Trusted host entrypoint for one exact reconnect transaction."""

        self._assert_thread()
        transactions = self.media_transactions
        if transactions is None:
            raise RuntimeError("Transactional classroom media is not bound")
        event = transactions.prepare_reconnect(credential, now=now)
        rendered = asdict(event)
        self._events.append(rendered)
        return rendered

    def prepare_classroom_media_disconnect(self) -> dict[str, object]:
        """Trusted host entrypoint for one exact provider disconnect transaction."""

        self._assert_thread()
        transactions = self.media_transactions
        if transactions is None:
            raise RuntimeError("Transactional classroom media is not bound")
        event = transactions.prepare_disconnect()
        rendered = asdict(event)
        self._events.append(rendered)
        return rendered

    def sync_composed_surfaces_language(self, language: UILanguage) -> None:
        self._assert_thread()
        if not isinstance(language, UILanguage):
            raise TypeError("full-product language must be UILanguage")
        self._rebuild_education_bridge(language)
        if self._teacher_state_provider is not None and self._teacher_dispatch is not None:
            projection = TeacherWebViewProjection.from_teaching_session(
                self._teacher_dispatch,
                self._teacher_state_provider,
            )
            self.teacher = TeacherWebViewBridge(projection, language=language)
        if self.media is not None:
            try:
                self.media.projection.set_language(language)
            except Exception:
                # A stale/broken realtime label/provider seam must not abort the
                # product-wide language switch. snapshot() will expose the media
                # recovery state while core chess and Education remain usable.
                pass

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
        if area == "media":
            if self.media is None:
                return self._error()
            if type(command) is str and command.startswith("media.provider_"):
                if self.media_transactions is None:
                    return self._error()
                return asdict(
                    self.media_transactions.dispatch_provider(command, payload)
                )
            return asdict(self.media.dispatch(command, payload))
        if area in {"classes", "education"}:
            if self.education is None:
                return self._error()
            return asdict(self.education.dispatch(command, payload))
        return super().browser_command(area, command, payload)

    def snapshot(self) -> dict[str, object]:
        self._assert_thread()
        result = super().snapshot()
        media_snapshot: dict[str, object] | None = None
        media_recovery_required = False
        media_transaction_active = (
            self.media_transactions is not None
            and self.media_transactions.binder.active_lease is not None
        )
        provider_recovery_required = (
            self.media_transactions is not None
            and self.media_transactions.binder.recovery_status is not None
        )
        if provider_recovery_required:
            # The provider execution arbiter is the global mutation gate.  Do
            # not export a stale projection containing actionable media buttons
            # while reconciliation is required.
            media_recovery_required = True
        elif media_transaction_active:
            # A provider mutation is still in flight.  Independent snapshot
            # refreshes must not repaint fresh action buttons around the one
            # globally serialized provider lease.
            pass
        elif self.media is not None:
            try:
                media_snapshot = self.media.projection.snapshot()
            except Exception:
                # Realtime/provider presentation failure must not make the chess
                # board, lesson records, or recovery surfaces disappear.
                media_recovery_required = True
        result.update(
            {
                "teacher": (
                    None
                    if self.teacher is None
                    else self.teacher.projection.snapshot(
                        language=self.shell.language.value
                    )
                ),
                "education": (
                    None
                    if self.education is None
                    else self.education.projection.snapshot()
                ),
                "media": media_snapshot,
                "product_status": {
                    "teacher_session_active": self.teacher is not None,
                    "education_available": self.education is not None,
                    "education_recovery_required": self._education_load_error,
                    "media_binding_active": self.media is not None,
                    "media_transaction_active": media_transaction_active,
                    "media_recovery_required": media_recovery_required,
                    # Composition is not an acceptance claim. Keep the
                    # whole-product transport gate truthful until real packaged
                    # two-client and NVDA qualification is recorded.
                    "media_provider_composed": self.media_transactions is not None,
                    "remote_transport": "not_approved",
                },
            }
        )
        return result
