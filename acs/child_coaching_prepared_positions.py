from __future__ import annotations

"""Child-coaching navigation over canonical D10 prepared teaching positions.

The D10 EducationWorkspace remains the only durable prepared-position authority.
This adapter owns only ephemeral current/next/previous selection and composes the
selected canonical TeachingPositionSource into ChildCoachingApplication.
"""

from dataclasses import dataclass
from typing import Callable

from .child_coaching_application import ChildCoachingApplication
from .education_workspace import EducationWorkspace, PreparedPosition
from .teaching_session import LessonSession, TeachingPositionSource


class ChildCoachingPreparedPositionError(ValueError):
    """Stable navigation/composition failure."""


@dataclass(frozen=True, slots=True)
class PreparedPositionSummary:
    position_id: str
    source_kind: str
    revision: int
    selected: bool

    @property
    def accessible_text(self) -> str:
        marker = "selected" if self.selected else "available"
        return (
            f"{self.position_id}, {self.source_kind}, "
            f"revision {self.revision}, {marker}"
        )


@dataclass(frozen=True, slots=True)
class PreparedPositionSnapshot:
    selected_position_id: str | None
    selected_index: int | None
    count: int
    positions: tuple[PreparedPositionSummary, ...]


class PreparedPositionNavigator:
    """Deterministic prepared-position cursor without duplicate persistence."""

    def __init__(
        self,
        application: ChildCoachingApplication,
        workspace_provider: Callable[[], EducationWorkspace],
    ) -> None:
        if type(application) is not ChildCoachingApplication:
            raise TypeError("application must be ChildCoachingApplication")
        if not callable(workspace_provider):
            raise TypeError("workspace_provider must be callable")
        self._application = application
        self._workspace_provider = workspace_provider
        self._selected_position_id: str | None = None

    def snapshot(self) -> PreparedPositionSnapshot:
        workspace = self._workspace()
        positions = workspace.prepared_positions
        selected = self._normalized_selected(positions)
        index = None
        if selected is not None:
            index = next(
                offset
                for offset, item in enumerate(positions)
                if item.position_id == selected
            )
        return PreparedPositionSnapshot(
            selected_position_id=selected,
            selected_index=index,
            count=len(positions),
            positions=tuple(
                PreparedPositionSummary(
                    position_id=item.position_id,
                    source_kind=item.source.kind.value,
                    revision=item.revision,
                    selected=item.position_id == selected,
                )
                for item in positions
            ),
        )

    def select(self, position_id: str) -> PreparedPositionSnapshot:
        if type(position_id) is not str:
            raise TypeError("position_id must be text")
        workspace = self._workspace()
        matches = tuple(
            item
            for item in workspace.prepared_positions
            if item.position_id == position_id
        )
        if len(matches) != 1:
            raise ChildCoachingPreparedPositionError(
                "prepared position does not exist"
            )
        self._selected_position_id = position_id
        return self.snapshot()

    def next(self) -> PreparedPositionSnapshot:
        return self._move(1)

    def previous(self) -> PreparedPositionSnapshot:
        return self._move(-1)

    def current(self) -> PreparedPosition:
        workspace = self._workspace()
        selected = self._normalized_selected(workspace.prepared_positions)
        if selected is None:
            message = (
                "no prepared positions are available"
                if not workspace.prepared_positions
                else "selected prepared position is unavailable; select again"
            )
            raise ChildCoachingPreparedPositionError(message)
        for item in workspace.prepared_positions:
            if item.position_id == selected:
                return item
        raise ChildCoachingPreparedPositionError(
            "selected prepared position is unavailable"
        )

    def current_source(self) -> TeachingPositionSource:
        return self.current().source

    def launch_current(
        self,
        template_id: str,
        *,
        session_id: str,
        lesson_id: str,
        student_ids: tuple[str, ...] = (),
        cohort_id: str | None = None,
        require_no_notation: bool = False,
        expected_template_revision: str | None = None,
        expected_position_revision: int | None = None,
    ) -> LessonSession:
        selected = self.current()
        if expected_position_revision is not None:
            if type(expected_position_revision) is not int or expected_position_revision < 0:
                raise ChildCoachingPreparedPositionError(
                    "expected prepared position revision must be a non-negative integer"
                )
            if selected.revision != expected_position_revision:
                raise ChildCoachingPreparedPositionError(
                    "prepared position changed; review it before launching"
                )
        source = selected.source
        return self._application.compile_session(
            template_id,
            session_id=session_id,
            lesson_id=lesson_id,
            source=source,
            student_ids=student_ids,
            cohort_id=cohort_id,
            require_no_notation=require_no_notation,
            expected_revision=expected_template_revision,
        )

    def _move(self, delta: int) -> PreparedPositionSnapshot:
        if delta not in {-1, 1}:
            raise ValueError("prepared-position delta must be -1 or 1")
        workspace = self._workspace()
        positions = workspace.prepared_positions
        selected = self._normalized_selected(positions)
        if selected is None:
            message = (
                "no prepared positions are available"
                if not workspace.prepared_positions
                else "selected prepared position is unavailable; select again"
            )
            raise ChildCoachingPreparedPositionError(message)
        index = next(
            offset
            for offset, item in enumerate(positions)
            if item.position_id == selected
        )
        target = index + delta
        if not 0 <= target < len(positions):
            raise ChildCoachingPreparedPositionError(
                "prepared position boundary reached"
            )
        self._selected_position_id = positions[target].position_id
        return self.snapshot()

    def _normalized_selected(
        self,
        positions: tuple[PreparedPosition, ...],
    ) -> str | None:
        ids = tuple(item.position_id for item in positions)
        if not ids:
            self._selected_position_id = None
            return None
        if self._selected_position_id is None:
            self._selected_position_id = ids[0]
            return self._selected_position_id
        if self._selected_position_id not in ids:
            return None
        return self._selected_position_id

    def _workspace(self) -> EducationWorkspace:
        workspace = self._workspace_provider()
        if type(workspace) is not EducationWorkspace:
            raise TypeError(
                "workspace_provider must return canonical EducationWorkspace"
            )
        return workspace
