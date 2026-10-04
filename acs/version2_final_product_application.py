from __future__ import annotations

"""Reachability composition for Teacher/Classroom/Education in the one V2 app."""

from collections.abc import Callable, Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any

from . import classroom_domain as cd
from .classroom_pairing import (
    PairingBatch,
    PairingMode,
    assert_pairing_scope,
    override_pairing,
    plan_pairings,
)
from .child_coaching_context import (
    ChildCoachingContextError,
    build_child_coaching_context,
    child_coaching_context_to_teacher_payload,
)
from .child_coaching_application import ChildCoachingApplication
from .child_coaching_prepared_positions import (
    ChildCoachingPreparedPositionError,
    PreparedPositionNavigator,
    PreparedPositionSnapshot,
)
from .classroom_prepared_position_deployment import (
    DeploymentTarget,
    PreparedPositionDeploymentBatch,
    assert_prepared_position_deployment_retry,
    assert_prepared_position_deployment_scope,
    plan_prepared_position_deployment as build_prepared_position_deployment,
    plan_uniform_prepared_position_deployment as build_uniform_prepared_position_deployment,
    resolve_prepared_position_source,
)
from .education_webview_bridge import EducationWebViewBridge
from .education_webview_projection import EducationWebViewProjection
from .education_workspace import EducationWorkspace
from .education_workspace_store import EducationWorkspaceStore
from .full_product_ui_shell import UILanguage
from .library_export_workspace import build_library_export_webview
from .search_service import GameSearchQuery
from .student_progress import StudentProgressLedger
from .student_progress_store import StudentProgressStore
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
        self._pairing_batch: PairingBatch | None = None
        self._prepared_position_deployment: PreparedPositionDeploymentBatch | None = None
        self._student_progress_store: StudentProgressStore | None = None
        self._student_progress_load_error = False
        self._child_coaching_application: ChildCoachingApplication | None = None
        self._prepared_position_navigator: PreparedPositionNavigator | None = None
        self._child_coaching_load_error = False

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
        # Pairing/deployment plans are exact projections of one D10 snapshot.
        # Invalidate them before any caller can reuse stale membership or
        # prepared-position revisions after an accepted workspace replacement.
        self._pairing_batch = None
        self._prepared_position_deployment = None
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
        self._pairing_batch = None
        self._prepared_position_deployment = None
        return state

    def stop_teaching_session(self) -> None:
        """Retire the application-owned live lesson and remove its Teacher bridge."""

        self._assert_thread()
        if self._teaching_state is None:
            raise RuntimeError("No application-owned teaching session is active")
        self._teaching_plan = None
        self._teaching_state = None
        self._pairing_batch = None
        self._prepared_position_deployment = None
        self._clear_teaching_binding()

    def unbind_teaching_session(self) -> None:
        """Unbind any trusted Teacher owner and discard only local live ownership."""

        self._assert_thread()
        self._teaching_plan = None
        self._teaching_state = None
        self._pairing_batch = None
        self._prepared_position_deployment = None
        self._clear_teaching_binding()

    def _classroom_orchestration_authorities(
        self,
    ) -> tuple[LessonSession, EducationWorkspace]:
        plan = self._teaching_plan
        state = self._teaching_state
        workspace = self._education_workspace
        if type(plan) is not LessonSession or type(state) is not TeachingSessionState:
            raise RuntimeError("No application-owned teaching session is active")
        if type(workspace) is not EducationWorkspace:
            raise RuntimeError("Education workspace is unavailable")
        validate_lesson_session_scope(plan, workspace.classroom)
        return plan, workspace

    @property
    def active_pairing_batch(self) -> PairingBatch | None:
        return self._pairing_batch

    @property
    def active_prepared_position_deployment(
        self,
    ) -> PreparedPositionDeploymentBatch | None:
        return self._prepared_position_deployment

    def plan_classroom_pairings(
        self,
        *,
        batch_id: str,
        game_session_ids: tuple[str, ...],
        student_ids: tuple[str, ...] | None = None,
        mode: PairingMode | str = PairingMode.SEQUENTIAL,
        ratings_by_student: Mapping[str, int] | None = None,
        base_seconds: int = 0,
        increment_seconds: int = 0,
    ) -> PairingBatch:
        """Plan one trusted pair-play batch against the live lesson/D10 scope."""

        self._assert_thread()
        plan, workspace = self._classroom_orchestration_authorities()
        candidate = plan_pairings(
            plan,
            workspace.classroom,
            batch_id=batch_id,
            game_session_ids=game_session_ids,
            student_ids=student_ids,
            mode=mode,
            ratings_by_student=ratings_by_student,
            base_seconds=base_seconds,
            increment_seconds=increment_seconds,
        )
        current_batch = self._pairing_batch
        if current_batch is not None and current_batch.batch_id == candidate.batch_id:
            assert_pairing_scope(current_batch, plan, workspace.classroom)
            if current_batch.digest != candidate.digest:
                raise RuntimeError("pairing batch id was reused with changed payload")
            return current_batch
        self._pairing_batch = candidate
        return candidate

    def override_classroom_pairing(
        self,
        *,
        pairing_id: str,
        white_student_id: str,
        black_student_id: str,
        base_seconds: int | None = None,
        increment_seconds: int | None = None,
    ) -> PairingBatch:
        """Apply a membership-preserving color/time override to the live batch."""

        self._assert_thread()
        plan, workspace = self._classroom_orchestration_authorities()
        current_batch = self._pairing_batch
        if current_batch is None:
            raise RuntimeError("No classroom pairing batch is active")
        assert_pairing_scope(current_batch, plan, workspace.classroom)
        updated = override_pairing(
            current_batch,
            pairing_id=pairing_id,
            white_student_id=white_student_id,
            black_student_id=black_student_id,
            base_seconds=base_seconds,
            increment_seconds=increment_seconds,
        )
        assert_pairing_scope(updated, plan, workspace.classroom)
        self._pairing_batch = updated
        return updated

    def plan_prepared_position_deployment(
        self,
        *,
        batch_id: str,
        position_by_student: Mapping[str, str],
        target: DeploymentTarget | None = None,
    ) -> PreparedPositionDeploymentBatch:
        """Plan exact prepared-position revisions for one trusted target."""

        self._assert_thread()
        plan, workspace = self._classroom_orchestration_authorities()
        candidate = build_prepared_position_deployment(
            plan,
            workspace,
            batch_id=batch_id,
            position_by_student=position_by_student,
            target=target,
        )
        current_batch = self._prepared_position_deployment
        if current_batch is not None and current_batch.batch_id == candidate.batch_id:
            assert_prepared_position_deployment_scope(current_batch, plan, workspace)
            assert_prepared_position_deployment_retry(current_batch, candidate)
            return current_batch
        self._prepared_position_deployment = candidate
        return candidate

    def plan_uniform_prepared_position_deployment(
        self,
        *,
        batch_id: str,
        position_id: str,
        target: DeploymentTarget | None = None,
    ) -> PreparedPositionDeploymentBatch:
        """Plan one durable prepared position for all students in a target."""

        self._assert_thread()
        plan, workspace = self._classroom_orchestration_authorities()
        candidate = build_uniform_prepared_position_deployment(
            plan,
            workspace,
            batch_id=batch_id,
            position_id=position_id,
            target=target,
        )
        current_batch = self._prepared_position_deployment
        if current_batch is not None and current_batch.batch_id == candidate.batch_id:
            assert_prepared_position_deployment_scope(current_batch, plan, workspace)
            assert_prepared_position_deployment_retry(current_batch, candidate)
            return current_batch
        self._prepared_position_deployment = candidate
        return candidate

    def resolve_prepared_position_assignment(
        self,
        assignment_id: str,
    ):
        """Resolve one assignment only after revalidating the complete live batch."""

        self._assert_thread()
        plan, workspace = self._classroom_orchestration_authorities()
        batch = self._prepared_position_deployment
        if batch is None:
            raise RuntimeError("No prepared-position deployment is active")
        return resolve_prepared_position_source(
            batch,
            assignment_id,
            plan,
            workspace,
        )

    def bind_child_coaching_application(
        self,
        application: ChildCoachingApplication,
    ) -> None:
        """Bind the canonical template service and D10-backed prepared cursor."""

        self._assert_thread()
        if type(application) is not ChildCoachingApplication:
            raise TypeError("child coaching application must be ChildCoachingApplication")
        if (
            self._child_coaching_application is not None
            and self._child_coaching_application is not application
        ):
            raise RuntimeError("Child coaching application is already bound")
        self._child_coaching_application = application
        if self._prepared_position_navigator is None:
            self._prepared_position_navigator = PreparedPositionNavigator(
                application,
                self._education_provider,
            )

    def open_child_coaching_catalog(self):
        """Open or seed the canonical template catalog without browser authority."""

        self._assert_thread()
        application = self._child_coaching_application
        if application is None:
            raise RuntimeError("Child coaching application is unavailable")
        try:
            catalog = application.open_catalog()
        except Exception:
            self._child_coaching_load_error = True
            raise RuntimeError("Child coaching templates require recovery") from None
        self._child_coaching_load_error = False
        return catalog

    def _prepared_position_owner(self) -> PreparedPositionNavigator:
        navigator = self._prepared_position_navigator
        if navigator is None:
            raise RuntimeError("Prepared-position coaching is unavailable")
        return navigator

    def prepared_position_snapshot(self) -> PreparedPositionSnapshot:
        self._assert_thread()
        return self._prepared_position_owner().snapshot()

    def select_prepared_position(self, position_id: str) -> PreparedPositionSnapshot:
        self._assert_thread()
        return self._prepared_position_owner().select(position_id)

    def next_prepared_position(self) -> PreparedPositionSnapshot:
        self._assert_thread()
        return self._prepared_position_owner().next()

    def previous_prepared_position(self) -> PreparedPositionSnapshot:
        self._assert_thread()
        return self._prepared_position_owner().previous()

    def start_prepared_child_lesson(
        self,
        template_id: str,
        *,
        session_id: str,
        lesson_id: str,
        student_ids: tuple[str, ...],
        cohort_id: str | None,
        require_no_notation: bool,
        expected_template_revision: str,
        expected_position_revision: int,
    ) -> TeachingSessionState:
        """Start a reviewed template from the exact selected D10 prepared source."""

        self._assert_thread()
        navigator = self._prepared_position_owner()
        try:
            plan = navigator.launch_current(
                template_id,
                session_id=session_id,
                lesson_id=lesson_id,
                student_ids=student_ids,
                cohort_id=cohort_id,
                require_no_notation=require_no_notation,
                expected_template_revision=expected_template_revision,
                expected_position_revision=expected_position_revision,
            )
        except ChildCoachingPreparedPositionError:
            raise
        except Exception:
            self._child_coaching_load_error = True
            raise
        self._child_coaching_load_error = False
        return self.start_teaching_session(plan)

    def bind_student_progress_store(self, store: StudentProgressStore) -> None:
        """Bind one local canonical progress store without making startup depend on it."""

        self._assert_thread()
        if not isinstance(store, StudentProgressStore):
            raise TypeError("student progress store must be StudentProgressStore")
        if self._student_progress_store is not None and self._student_progress_store is not store:
            raise RuntimeError("Student progress store is already bound")
        self._student_progress_store = store
        try:
            store.load()
        except Exception:
            # Corrupt/unreadable progress is not a clean first run. Keep the
            # core product usable but make coaching context fail closed until a
            # later successful reread proves one canonical ledger.
            self._student_progress_load_error = True
        else:
            self._student_progress_load_error = False

    def current_student_coaching_context(
        self,
        student_id: str,
    ) -> dict[str, object]:
        """Return coach-only aggregate progress for one student in the live lesson."""

        self._assert_thread()
        plan, workspace = self._classroom_orchestration_authorities()
        if type(student_id) is not str or student_id not in plan.student_ids:
            raise RuntimeError("Student is outside the active teaching session")
        store = self._student_progress_store
        if store is None:
            raise RuntimeError("Student progress store is unavailable")
        try:
            loaded = store.load()
        except Exception:
            self._student_progress_load_error = True
            raise RuntimeError("Student progress requires recovery") from None
        self._student_progress_load_error = False
        ledger = StudentProgressLedger() if loaded is None else loaded.ledger
        try:
            context = build_child_coaching_context(
                workspace.classroom,
                ledger,
                student_id=student_id,
                session_id=plan.session_id,
                language=self.shell.language,
            )
        except ChildCoachingContextError as exc:
            raise RuntimeError("Student coaching context is unavailable") from exc
        return child_coaching_context_to_teacher_payload(context)

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
                    "classroom_pairing_planned": self._pairing_batch is not None,
                    "classroom_pair_count": (
                        0 if self._pairing_batch is None else len(self._pairing_batch.pairings)
                    ),
                    "prepared_position_deployment_planned": (
                        self._prepared_position_deployment is not None
                    ),
                    "prepared_position_assignment_count": (
                        0
                        if self._prepared_position_deployment is None
                        else len(self._prepared_position_deployment.assignments)
                    ),
                    "student_progress_available": (
                        self._student_progress_store is not None
                        and not self._student_progress_load_error
                    ),
                    "student_progress_recovery_required": (
                        self._student_progress_load_error
                    ),
                    "child_coaching_available": (
                        self._child_coaching_application is not None
                        and not self._child_coaching_load_error
                    ),
                    "child_coaching_recovery_required": self._child_coaching_load_error,
                    "prepared_position_navigation_available": (
                        self._prepared_position_navigator is not None
                    ),
                    "remote_transport": "not_approved",
                },
            }
        )
        return result
