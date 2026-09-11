from __future__ import annotations

"""Reachability composition for Teacher/Classroom/Education in the one V2 app."""

from collections.abc import Callable, Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any

from . import classroom_domain as cd
from .education_webview_bridge import EducationWebViewBridge
from .education_webview_projection import EducationWebViewProjection
from .education_workspace import EducationWorkspace
from .education_workspace_store import EducationWorkspaceStore
from .full_product_ui_shell import UILanguage
from .library_export_workspace import build_library_export_webview
from .search_service import GameSearchQuery
from .teacher_webview_bridge import TeacherWebViewBridge
from .teacher_webview_projection import TeacherWebViewProjection
from .teaching_session import TeachingSessionState
from .version2_application import Version2Application
from .version2_final_product_profile import (
    build_final_product_router,
    build_final_product_shell,
    build_final_product_webview_adapter,
)


class Version2FinalProductApplication(Version2Application):
    """One application authority with bounded D09/D10 presentation seams.

    Teacher state remains absent until a trusted host binds an actual canonical
    ``TeachingSessionState`` provider. Education state is loaded from the durable
    D10 workspace store. Corrupt/unreadable Education state is never overwritten
    automatically and does not prevent the core chess product from starting.
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
        """Trusted CAS publication seam for a future canonical editor owner."""

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

    def bind_teaching_session(
        self,
        state_provider: Callable[[], TeachingSessionState],
        dispatch: Callable[[str, Mapping[str, object]], object],
    ) -> None:
        """Bind D09 UI directly over a trusted canonical teaching-session owner."""

        self._assert_thread()
        projection = TeacherWebViewProjection.from_teaching_session(
            dispatch,
            state_provider,
        )
        self._teacher_state_provider = state_provider
        self._teacher_dispatch = dispatch
        self.teacher = TeacherWebViewBridge(
            projection,
            language=self.shell.language,
        )

    def unbind_teaching_session(self) -> None:
        self._assert_thread()
        self.teacher = None
        self._teacher_state_provider = None
        self._teacher_dispatch = None

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
            if self.education is None:
                return self._error()
            return asdict(self.education.dispatch(command, payload))
        return super().browser_command(area, command, payload)

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
                "education": (
                    None
                    if self.education is None
                    else self.education.projection.snapshot()
                ),
                "product_status": {
                    "teacher_session_active": self.teacher is not None,
                    "education_available": self.education is not None,
                    "education_recovery_required": self._education_load_error,
                    "remote_transport": "not_approved",
                },
            }
        )
        return result
