from __future__ import annotations

"""Read-only Universal Agent access to canonical classroom presentation status.

This bridge consumes only the already-sanitized Version2FinalProductApplication
snapshot. It does not read Classroom persistence directly, expose student records,
parse chess state, or mutate a lesson.
"""

from collections.abc import Callable, Mapping

from .agent_tools import ToolExecutor, ToolSpec


_MAX_STATUS_TEXT = 64
_MAX_SUMMARY_TEXT = 4000
_MAX_FEEDBACK_ITEMS = 10
_MAX_FEEDBACK_TEXT = 512


class AgentClassroomToolsError(ValueError):
    pass


def _exact_bool(value: object, *, name: str) -> bool:
    if type(value) is not bool:
        raise AgentClassroomToolsError(f"{name} must be boolean")
    return value


def _bounded_text(
    value: object,
    *,
    name: str,
    maximum: int,
    allow_empty: bool = False,
) -> str:
    if type(value) is not str:
        raise AgentClassroomToolsError(f"{name} must be text")
    text = value.strip()
    if not text and not allow_empty:
        raise AgentClassroomToolsError(f"{name} must not be empty")
    if len(text) > maximum:
        raise AgentClassroomToolsError(f"{name} is too long")
    return text


class AgentClassroomTools:
    """Expose bounded classroom/session presentation truth to the Agent."""

    def __init__(
        self,
        snapshot_provider: Callable[[], Mapping[str, object]],
    ) -> None:
        if not callable(snapshot_provider):
            raise TypeError("snapshot_provider must be callable")
        self._snapshot_provider = snapshot_provider

    def status(self) -> dict[str, object]:
        root = self._snapshot_provider()
        if type(root) is not dict:
            raise AgentClassroomToolsError(
                "application snapshot must be a plain object"
            )

        raw_status = root.get("product_status")
        if raw_status is None:
            return {"available": False}
        if type(raw_status) is not dict:
            raise AgentClassroomToolsError(
                "product_status must be a plain object"
            )

        active = _exact_bool(
            raw_status.get("teacher_session_active"),
            name="teacher_session_active",
        )
        education_available = _exact_bool(
            raw_status.get("education_available"),
            name="education_available",
        )
        recovery_required = _exact_bool(
            raw_status.get("education_recovery_required"),
            name="education_recovery_required",
        )
        remote_transport = _bounded_text(
            raw_status.get("remote_transport"),
            name="remote_transport",
            maximum=_MAX_STATUS_TEXT,
        )

        raw_teacher = root.get("teacher")
        if active != (raw_teacher is not None):
            raise AgentClassroomToolsError(
                "teacher session availability is inconsistent"
            )

        teacher: dict[str, object] | None = None
        if raw_teacher is not None:
            if type(raw_teacher) is not dict:
                raise AgentClassroomToolsError(
                    "teacher snapshot must be a plain object"
                )
            raw_board = raw_teacher.get("board")
            if type(raw_board) is not dict:
                raise AgentClassroomToolsError(
                    "teacher board presentation must be a plain object"
                )

            raw_feedback = raw_teacher.get("feedback", ())
            if type(raw_feedback) not in (tuple, list):
                raise AgentClassroomToolsError(
                    "teacher feedback must be a passive sequence"
                )
            if len(raw_feedback) > _MAX_FEEDBACK_ITEMS:
                raise AgentClassroomToolsError(
                    "teacher feedback exceeds the bounded presentation window"
                )
            feedback = [
                _bounded_text(
                    item,
                    name="teacher feedback item",
                    maximum=_MAX_FEEDBACK_TEXT,
                    allow_empty=True,
                )
                for item in raw_feedback
            ]

            teacher = {
                "mode": _bounded_text(
                    raw_teacher.get("mode"),
                    name="teacher mode",
                    maximum=_MAX_STATUS_TEXT,
                ),
                "boardPermission": _bounded_text(
                    raw_board.get("permission"),
                    name="teacher board permission",
                    maximum=_MAX_STATUS_TEXT,
                ),
                "engineVisibility": _bounded_text(
                    raw_board.get("engine_visibility"),
                    name="teacher engine visibility",
                    maximum=_MAX_STATUS_TEXT,
                ),
                "accessibleSummary": _bounded_text(
                    raw_teacher.get("accessible_summary", ""),
                    name="teacher accessible summary",
                    maximum=_MAX_SUMMARY_TEXT,
                    allow_empty=True,
                ),
                "feedback": feedback,
            }

        return {
            "available": True,
            "teacherSessionActive": active,
            "educationAvailable": education_available,
            "educationRecoveryRequired": recovery_required,
            "remoteTransport": remote_transport,
            "teacher": teacher,
        }

    def register(self, executor: ToolExecutor) -> ToolSpec:
        if type(executor) is not ToolExecutor:
            raise TypeError("executor must be ToolExecutor")

        async def status(arguments: Mapping[str, object]) -> object:
            if arguments:
                raise AgentClassroomToolsError(
                    "classroom.status accepts no arguments"
                )
            return self.status()

        spec = ToolSpec(
            "classroom.status",
            (
                "Read bounded classroom/teaching presentation status without "
                "student records or independent chess state."
            ),
        )
        executor.register(spec, status)
        return spec
