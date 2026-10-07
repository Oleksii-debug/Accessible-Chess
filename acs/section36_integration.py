from __future__ import annotations

"""Section 36 late cross-product integration boundaries.

This module intentionally owns no chess, Classroom, Media, account, workspace,
or tactile truth. It composes already-authoritative typed boundaries and keeps
all cross-surface actions fail-closed.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from .agent_tools import ToolExecutor, ToolRisk, ToolSpec
from .media_application import MediaApplicationService
from .remote_session import RemoteSessionState
from .tactile_sync import TactileSyncController, TactileSyncSnapshot
from .teaching_session import TeachingSessionState


_MAX_ID = 256
_MAX_PERMISSIONS = 128
_MAX_ACTIONS = 128


class Section36IntegrationError(ValueError):
    """Stable failure at the late cross-product integration boundary."""


def _optional_id(value: object, name: str) -> str | None:
    if value is None:
        return None
    if type(value) is not str or not value or value != value.strip():
        raise Section36IntegrationError(f"{name} must be canonical text or null")
    if len(value) > _MAX_ID:
        raise Section36IntegrationError(f"{name} is too long")
    return value


def _permission(value: object) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise Section36IntegrationError("permission must be canonical text")
    if len(value) > _MAX_ID or any(ch.isspace() for ch in value):
        raise Section36IntegrationError("permission is invalid")
    return value


@dataclass(frozen=True, slots=True)
class AccountWorkspaceSnapshot:
    """Detached non-secret view supplied by the canonical account/workspace owner."""

    signed_in: bool
    account_id: str | None
    organization_id: str | None
    workspace_id: str | None
    workspace_revision: int
    permissions: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if type(self.signed_in) is not bool:
            raise Section36IntegrationError("signed_in must be boolean")
        object.__setattr__(self, "account_id", _optional_id(self.account_id, "account_id"))
        object.__setattr__(
            self,
            "organization_id",
            _optional_id(self.organization_id, "organization_id"),
        )
        object.__setattr__(
            self,
            "workspace_id",
            _optional_id(self.workspace_id, "workspace_id"),
        )
        if self.signed_in != (self.account_id is not None):
            raise Section36IntegrationError(
                "signed_in and account_id must describe the same account state"
            )
        if self.workspace_id is not None and not self.signed_in:
            raise Section36IntegrationError(
                "workspace access requires an authenticated account"
            )
        if type(self.workspace_revision) is not int or self.workspace_revision < 0:
            raise Section36IntegrationError(
                "workspace_revision must be a non-negative exact integer"
            )
        if type(self.permissions) is not frozenset:
            raise Section36IntegrationError("permissions must be a frozenset")
        if len(self.permissions) > _MAX_PERMISSIONS:
            raise Section36IntegrationError("too many account/workspace permissions")
        object.__setattr__(
            self,
            "permissions",
            frozenset(_permission(value) for value in self.permissions),
        )


AuthorizationPolicy = Callable[[str, AccountWorkspaceSnapshot], bool]


class AgentAccountWorkspaceTools:
    """Authorized, non-secret Agent reads over Section-31 account/workspace truth."""

    def __init__(
        self,
        snapshot_provider: Callable[[], AccountWorkspaceSnapshot],
        authorization: AuthorizationPolicy,
    ) -> None:
        if not callable(snapshot_provider):
            raise TypeError("snapshot_provider must be callable")
        if not callable(authorization):
            raise TypeError("authorization must be callable")
        self._snapshot_provider = snapshot_provider
        self._authorization = authorization

    def _snapshot(self, permission: str) -> AccountWorkspaceSnapshot:
        snapshot = self._snapshot_provider()
        if type(snapshot) is not AccountWorkspaceSnapshot:
            raise Section36IntegrationError(
                "account/workspace authority returned an invalid snapshot"
            )
        try:
            allowed = self._authorization(permission, snapshot)
        except Exception as exc:
            raise Section36IntegrationError("authorization check failed") from exc
        if type(allowed) is not bool or not allowed or permission not in snapshot.permissions:
            raise Section36IntegrationError("account/workspace access is not authorized")
        return snapshot

    def account_status(self) -> dict[str, object]:
        snapshot = self._snapshot("account.read")
        return {
            "signedIn": snapshot.signed_in,
            "accountId": snapshot.account_id,
            "organizationId": snapshot.organization_id,
        }

    def workspace_status(self) -> dict[str, object]:
        snapshot = self._snapshot("workspace.read")
        return {
            "workspaceId": snapshot.workspace_id,
            "workspaceRevision": snapshot.workspace_revision,
            "organizationId": snapshot.organization_id,
        }

    def register(self, executor: ToolExecutor) -> tuple[ToolSpec, ToolSpec]:
        if type(executor) is not ToolExecutor:
            raise TypeError("executor must be ToolExecutor")

        async def account_status(arguments: Mapping[str, object]) -> object:
            if arguments:
                raise Section36IntegrationError("account.status accepts no arguments")
            return self.account_status()

        async def workspace_status(arguments: Mapping[str, object]) -> object:
            if arguments:
                raise Section36IntegrationError("workspace.status accepts no arguments")
            return self.workspace_status()

        specs = (
            ToolSpec(
                "account.status",
                "Read authorized non-secret account status from the canonical account authority.",
            ),
            ToolSpec(
                "workspace.status",
                "Read authorized workspace identity/revision without credentials or private records.",
            ),
        )
        executor.register(specs[0], account_status)
        executor.register(specs[1], workspace_status)
        return specs


TeacherDispatch = Callable[[str, Mapping[str, object]], object]


class TeacherAssistantWorkflow:
    """Typed Teacher-Assistant lane over one canonical TeachingSession owner."""

    def __init__(
        self,
        state_provider: Callable[[], TeachingSessionState],
        dispatch: TeacherDispatch,
        *,
        permitted_actions: frozenset[str],
    ) -> None:
        if not callable(state_provider):
            raise TypeError("state_provider must be callable")
        if not callable(dispatch):
            raise TypeError("dispatch must be callable")
        if type(permitted_actions) is not frozenset or not permitted_actions:
            raise TypeError("permitted_actions must be a non-empty frozenset")
        if len(permitted_actions) > _MAX_ACTIONS:
            raise Section36IntegrationError("too many Teacher Assistant actions")
        for action in permitted_actions:
            if (
                type(action) is not str
                or not action.startswith("teacher.")
                or action != action.strip()
            ):
                raise Section36IntegrationError(
                    "Teacher Assistant actions must be canonical teacher.* identifiers"
                )
        self._state_provider = state_provider
        self._dispatch = dispatch
        self._permitted_actions = permitted_actions

    def status(self) -> dict[str, object]:
        state = self._state_provider()
        if type(state) is not TeachingSessionState:
            raise Section36IntegrationError(
                "Teacher Assistant requires canonical TeachingSessionState"
            )
        return {
            "sessionId": state.session_id,
            "phase": state.phase.value,
            "revision": state.revision,
            "stepIndex": state.step_index,
            "activeStudentId": state.active_student_id,
            "boardPermission": state.presentation.board_permission.value,
            "engineVisibility": state.presentation.engine_visibility.value,
        }

    def apply(
        self,
        action_id: object,
        payload: object,
        expected_revision: object,
    ) -> dict[str, object]:
        if type(action_id) is not str or action_id not in self._permitted_actions:
            raise Section36IntegrationError("Teacher Assistant action is not permitted")
        if type(expected_revision) is not int or expected_revision < 0:
            raise Section36IntegrationError(
                "expected_revision must be a non-negative exact integer"
            )
        if not isinstance(payload, Mapping) or any(
            type(key) is not str for key in payload
        ):
            raise Section36IntegrationError("Teacher Assistant payload must be an object")

        before = self._state_provider()
        if type(before) is not TeachingSessionState:
            raise Section36IntegrationError(
                "Teacher Assistant requires canonical TeachingSessionState"
            )
        if before.revision != expected_revision:
            raise Section36IntegrationError("stale TeachingSession revision")

        self._dispatch(action_id, dict(payload))

        after = self._state_provider()
        if type(after) is not TeachingSessionState:
            raise Section36IntegrationError(
                "Teacher Assistant owner returned an invalid post-action state"
            )
        if after.session_id != before.session_id:
            raise Section36IntegrationError("Teacher Assistant changed session authority")
        if after.position_fen != before.position_fen:
            raise Section36IntegrationError(
                "Teacher Assistant action mutated canonical chess position"
            )
        if after.revision < before.revision:
            raise Section36IntegrationError(
                "Teacher Assistant revision moved backwards"
            )
        return {
            "applied": True,
            "actionId": action_id,
            "revision": after.revision,
            "sessionId": after.session_id,
        }

    def register(self, executor: ToolExecutor) -> tuple[ToolSpec, ToolSpec]:
        if type(executor) is not ToolExecutor:
            raise TypeError("executor must be ToolExecutor")

        async def status(arguments: Mapping[str, object]) -> object:
            if arguments:
                raise Section36IntegrationError(
                    "classroom.teacher_assistant.status accepts no arguments"
                )
            return self.status()

        async def apply(arguments: Mapping[str, object]) -> object:
            if set(arguments) != {"action_id", "payload", "expected_revision"}:
                raise Section36IntegrationError(
                    "Teacher Assistant apply payload shape is invalid"
                )
            return self.apply(
                arguments["action_id"],
                arguments["payload"],
                arguments["expected_revision"],
            )

        specs = (
            ToolSpec(
                "classroom.teacher_assistant.status",
                "Read bounded Teacher Assistant workflow state from canonical Classroom.",
            ),
            ToolSpec(
                "classroom.teacher_assistant.apply",
                "Apply one host-permitted presentation-only Teacher workflow action.",
                risk=ToolRisk.LOCAL_WRITE,
                input_schema={
                    "action_id": "permitted teacher.* action identifier",
                    "payload": "typed action payload object",
                    "expected_revision": "non-negative TeachingSession revision",
                },
            ),
        )
        executor.register(specs[0], status)
        executor.register(specs[1], apply)
        return specs


MediaRefResolver = Callable[[str], str]


class CrossSurfaceTactileBridge:
    """Synchronize tactile presentation from existing Media/Classroom/remote owners."""

    def __init__(
        self,
        tactile: TactileSyncController,
        *,
        media_provider: Callable[[], MediaApplicationService] | None = None,
        media_ref_to_fen: MediaRefResolver | None = None,
        classroom_state_provider: Callable[[], TeachingSessionState] | None = None,
        remote_state_provider: Callable[[], RemoteSessionState] | None = None,
    ) -> None:
        if not isinstance(tactile, TactileSyncController):
            raise TypeError("tactile must be TactileSyncController")
        if media_provider is not None and not callable(media_provider):
            raise TypeError("media_provider must be callable or None")
        if media_ref_to_fen is not None and not callable(media_ref_to_fen):
            raise TypeError("media_ref_to_fen must be callable or None")
        if (media_provider is None) != (media_ref_to_fen is None):
            raise TypeError(
                "media_provider and media_ref_to_fen must be configured together"
            )
        if classroom_state_provider is not None and not callable(
            classroom_state_provider
        ):
            raise TypeError("classroom_state_provider must be callable or None")
        if remote_state_provider is not None and not callable(remote_state_provider):
            raise TypeError("remote_state_provider must be callable or None")
        self._tactile = tactile
        self._media_provider = media_provider
        self._media_ref_to_fen = media_ref_to_fen
        self._classroom_state_provider = classroom_state_provider
        self._remote_state_provider = remote_state_provider

    @staticmethod
    def _payload(
        source: str,
        source_revision: int,
        snapshot: TactileSyncSnapshot,
    ) -> dict[str, object]:
        return {
            "source": source,
            "sourceRevision": source_revision,
            "tactileSyncRevision": snapshot.sync_revision,
            "sceneSequence": snapshot.scene_sequence,
            "canonicalFen": snapshot.canonical_fen,
            "status": snapshot.state.value,
        }

    def status(self) -> dict[str, object]:
        snapshot = self._tactile.snapshot()
        return {
            "status": snapshot.state.value,
            "source": None if snapshot.source is None else snapshot.source.value,
            "tactileSyncRevision": snapshot.sync_revision,
            "sceneSequence": snapshot.scene_sequence,
            "canonicalFen": snapshot.canonical_fen,
        }

    def sync_media(self) -> dict[str, object]:
        provider = self._media_provider
        resolver = self._media_ref_to_fen
        if provider is None or resolver is None:
            raise Section36IntegrationError("Media tactile source is unavailable")
        application = provider()
        if not isinstance(application, MediaApplicationService):
            raise Section36IntegrationError(
                "media_provider must return MediaApplicationService"
            )
        before = application.snapshot()
        chess_ref = before.synchronized_chess_ref
        if not before.can_restore or type(chess_ref) is not str or not chess_ref:
            raise Section36IntegrationError(
                "Media has no confirmed canonical position for tactile output"
            )
        try:
            fen = resolver(chess_ref)
        except Exception as exc:
            raise Section36IntegrationError(
                "Media chess reference could not be resolved"
            ) from exc
        if type(fen) is not str:
            raise Section36IntegrationError(
                "Media chess reference resolver must return canonical FEN text"
            )
        tactile = self._tactile.sync_position(
            fen,
            source_revision=before.revision,
        )
        if application.snapshot() != before:
            raise Section36IntegrationError(
                "tactile Media refresh mutated Media application state"
            )
        return self._payload("media", before.revision, tactile)

    def sync_classroom(self) -> dict[str, object]:
        provider = self._classroom_state_provider
        if provider is None:
            raise Section36IntegrationError("Classroom tactile source is unavailable")
        state = provider()
        if type(state) is not TeachingSessionState:
            raise Section36IntegrationError(
                "Classroom tactile source must return TeachingSessionState"
            )
        tactile = self._tactile.sync_position(
            state.position_fen,
            source_revision=state.revision,
        )
        return self._payload("classroom", state.revision, tactile)

    def sync_remote(self) -> dict[str, object]:
        provider = self._remote_state_provider
        if provider is None:
            raise Section36IntegrationError("remote tactile source is unavailable")
        state = provider()
        if type(state) is not RemoteSessionState:
            raise Section36IntegrationError(
                "remote tactile source must return RemoteSessionState"
            )
        tactile = self._tactile.sync_position(
            state.position_fen,
            source_revision=state.last_sequence,
        )
        return self._payload("remote", state.last_sequence, tactile)


class AgentTactileTools:
    """Permitted Agent tactile actions that only refresh presentation from owners."""

    def __init__(self, bridge: CrossSurfaceTactileBridge) -> None:
        if type(bridge) is not CrossSurfaceTactileBridge:
            raise TypeError("bridge must be CrossSurfaceTactileBridge")
        self._bridge = bridge

    def register(self, executor: ToolExecutor) -> tuple[ToolSpec, ...]:
        if type(executor) is not ToolExecutor:
            raise TypeError("executor must be ToolExecutor")

        specs_and_actions = (
            (
                ToolSpec(
                    "tactile.status",
                    "Read current tactile presentation synchronization status.",
                ),
                self._bridge.status,
            ),
            (
                ToolSpec(
                    "tactile.refresh_media",
                    "Refresh tactile presentation from confirmed canonical Media state.",
                    risk=ToolRisk.LOCAL_WRITE,
                ),
                self._bridge.sync_media,
            ),
            (
                ToolSpec(
                    "tactile.refresh_classroom",
                    "Refresh tactile presentation from canonical Classroom state.",
                    risk=ToolRisk.LOCAL_WRITE,
                ),
                self._bridge.sync_classroom,
            ),
            (
                ToolSpec(
                    "tactile.refresh_remote",
                    "Refresh tactile presentation from canonical remote Classroom state.",
                    risk=ToolRisk.LOCAL_WRITE,
                ),
                self._bridge.sync_remote,
            ),
        )
        for spec, action in specs_and_actions:
            async def handler(
                arguments: Mapping[str, object],
                action: Callable[[], object] = action,
            ) -> object:
                if arguments:
                    raise Section36IntegrationError("tactile tool accepts no arguments")
                return action()

            executor.register(spec, handler)
        return tuple(spec for spec, _action in specs_and_actions)


class Section36AgentIntegration:
    """Single registration point for late Agent/Classroom/account/tactile tools."""

    def __init__(
        self,
        *,
        account_workspace: AgentAccountWorkspaceTools,
        teacher_assistant: TeacherAssistantWorkflow,
        tactile: AgentTactileTools,
    ) -> None:
        if type(account_workspace) is not AgentAccountWorkspaceTools:
            raise TypeError("account_workspace must be AgentAccountWorkspaceTools")
        if type(teacher_assistant) is not TeacherAssistantWorkflow:
            raise TypeError("teacher_assistant must be TeacherAssistantWorkflow")
        if type(tactile) is not AgentTactileTools:
            raise TypeError("tactile must be AgentTactileTools")
        self._account_workspace = account_workspace
        self._teacher_assistant = teacher_assistant
        self._tactile = tactile

    def register(self, executor: ToolExecutor) -> tuple[ToolSpec, ...]:
        before = {spec.tool_id for spec in executor.specs()}
        self._account_workspace.register(executor)
        self._teacher_assistant.register(executor)
        self._tactile.register(executor)
        return tuple(
            spec for spec in executor.specs() if spec.tool_id not in before
        )


__all__ = [
    "AccountWorkspaceSnapshot",
    "AgentAccountWorkspaceTools",
    "AgentTactileTools",
    "CrossSurfaceTactileBridge",
    "Section36AgentIntegration",
    "Section36IntegrationError",
    "TeacherAssistantWorkflow",
]
