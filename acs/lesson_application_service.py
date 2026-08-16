from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Mapping, Sequence

from .child_coaching_ui import DEFAULT_LESSON_TEMPLATES, LessonTemplate
from .lesson_plan import (
    AssignmentTarget,
    ClassroomPairing,
    LessonItem,
    LessonItemKind,
    LessonPlan,
    LessonPosition,
    PositionAssignment,
)
from .lesson_session_storage import LessonSessionSQLiteStore, PairingSessionBatch, PairingSessionRecord
from .lesson_storage import (
    DeploymentBatch,
    DeploymentRecord,
    DeploymentTarget,
    LessonRevision,
    LessonSQLiteStore,
)
from .lesson_template_storage import (
    LessonTemplatePreset,
    LessonTemplateSQLiteStore,
    RotationRevision,
    RotationRoundRecord,
    TemplateRevision,
)

FenValidator = Callable[[str], None]


@dataclass(frozen=True)
class LessonRecoverySnapshot:
    classroom_session_id: str
    deployments: tuple[DeploymentRecord, ...]
    pairings: tuple[PairingSessionRecord, ...]
    rotations: tuple[RotationRoundRecord, ...]


class LessonApplicationService:
    """Application boundary for persisted lesson/classroom orchestration.

    The service composes existing versioned stores and shared-Core FEN validation.
    It owns no Board, legality, move history, clock, media or realtime transport.
    Stable storage identities are returned unchanged so UI/reconnect flows can
    recover without inventing a second chess-state authority.
    """

    def __init__(
        self,
        *,
        lesson_store: LessonSQLiteStore,
        template_store: LessonTemplateSQLiteStore,
        session_store: LessonSessionSQLiteStore,
        fen_validator: FenValidator,
    ) -> None:
        if not callable(fen_validator):
            raise TypeError("fen_validator must be callable")
        self.lesson_store = lesson_store
        self.template_store = template_store
        self.session_store = session_store
        self._fen_validator = fen_validator

    def ensure_default_templates(self) -> tuple[TemplateRevision, ...]:
        presets = tuple(
            LessonTemplatePreset(template, level="beginner", is_preset=True)
            for template in DEFAULT_LESSON_TEMPLATES
        )
        return self.template_store.ensure_presets(presets)

    def save_new_template(
        self, template: LessonTemplate, *, level: str, is_preset: bool = False
    ) -> TemplateRevision:
        return self.template_store.save_new_template(
            LessonTemplatePreset(template, level=level, is_preset=is_preset)
        )

    def update_template(
        self,
        template: LessonTemplate,
        *,
        level: str,
        expected_revision: int,
        is_preset: bool = False,
    ) -> TemplateRevision:
        return self.template_store.update_template(
            LessonTemplatePreset(template, level=level, is_preset=is_preset),
            expected_revision=expected_revision,
        )

    def load_template(self, template_id: str) -> tuple[LessonTemplatePreset, TemplateRevision]:
        return self.template_store.load_template(template_id)

    def materialize_template(
        self,
        template_id: str,
        *,
        lesson_id: str,
        title: str,
        positions: Sequence[LessonPosition] = (),
        assignments: Sequence[PositionAssignment] = (),
        position_bindings: Mapping[str, str] | None = None,
    ) -> LessonPlan:
        preset, _ = self.template_store.load_template(template_id)
        bindings = dict(position_bindings or {})
        known_positions = {position.position_id for position in positions}
        items: list[LessonItem] = []
        for block in preset.template.blocks:
            position_id = bindings.get(block.block_id)
            if block.kind is LessonItemKind.POSITION:
                if position_id is None:
                    raise ValueError(
                        f"position template block requires binding: {block.block_id}"
                    )
                if position_id not in known_positions:
                    raise ValueError(
                        f"position template block references unknown position: {position_id}"
                    )
            elif position_id is not None:
                raise ValueError(
                    f"non-position template block cannot bind a position: {block.block_id}"
                )
            items.append(
                LessonItem(
                    block.block_id,
                    block.kind,
                    block.title,
                    block.duration_minutes,
                    position_id,
                    "notation required" if block.notation_required else "",
                )
            )
        return LessonPlan(
            lesson_id,
            title,
            preset.template.age_band,
            preset.level,
            tuple(items),
            tuple(positions),
            tuple(assignments),
        )

    def save_new_plan(self, plan: LessonPlan) -> LessonRevision:
        self._validate_plan_fens(plan)
        return self.lesson_store.save_new(plan)

    def update_plan(self, plan: LessonPlan, *, expected_revision: int) -> LessonRevision:
        self._validate_plan_fens(plan)
        return self.lesson_store.update(plan, expected_revision=expected_revision)

    def load_plan(self, lesson_id: str) -> tuple[LessonPlan, LessonRevision]:
        return self.lesson_store.load(lesson_id)

    def deploy_assignment(
        self,
        *,
        lesson_id: str,
        assignment_id: str,
        classroom_session_id: str,
        batch_id: str,
        first_sequence_no: int,
    ) -> DeploymentBatch:
        plan, _ = self.lesson_store.load(lesson_id)
        assignment = next(
            (item for item in plan.assignments if item.assignment_id == assignment_id),
            None,
        )
        if assignment is None:
            raise ValueError(f"unknown lesson assignment: {assignment_id}")
        targets = self._targets_for_assignment(assignment, classroom_session_id)
        return self.lesson_store.record_deployment_batch(
            batch_id=batch_id,
            lesson_id=lesson_id,
            assignment_id=assignment.assignment_id,
            position_id=assignment.position_id,
            session_id=classroom_session_id,
            targets=targets,
            first_sequence_no=first_sequence_no,
        )

    def deploy_demonstration_position(
        self,
        *,
        lesson_id: str,
        position_id: str,
        classroom_session_id: str,
        batch_id: str,
        first_sequence_no: int,
    ) -> DeploymentBatch:
        plan, _ = self.lesson_store.load(lesson_id)
        if position_id not in plan.position_map():
            raise ValueError(f"unknown lesson position: {position_id}")
        return self.lesson_store.record_deployment_batch(
            batch_id=batch_id,
            lesson_id=lesson_id,
            assignment_id=None,
            position_id=position_id,
            session_id=classroom_session_id,
            targets=(DeploymentTarget("demonstration", classroom_session_id),),
            first_sequence_no=first_sequence_no,
        )

    def record_pairings(
        self,
        *,
        batch_id: str,
        lesson_id: str,
        classroom_session_id: str,
        pairings: Iterable[ClassroomPairing],
        game_session_ids: Iterable[str],
    ) -> PairingSessionBatch:
        pairing_tuple = tuple(pairings)
        self._validate_pairing_fens(pairing_tuple)
        return self.session_store.record_pairing_batch(
            batch_id=batch_id,
            lesson_id=lesson_id,
            classroom_session_id=classroom_session_id,
            pairings=pairing_tuple,
            game_session_ids=tuple(game_session_ids),
        )

    def save_rotation(self, record: RotationRoundRecord) -> RotationRevision:
        return self.template_store.save_new_rotation(record)

    def update_rotation(
        self, record: RotationRoundRecord, *, expected_revision: int
    ) -> RotationRevision:
        return self.template_store.update_rotation(
            record, expected_revision=expected_revision
        )

    def recover_classroom(self, classroom_session_id: str) -> LessonRecoverySnapshot:
        return LessonRecoverySnapshot(
            classroom_session_id,
            self.lesson_store.deployment_timeline(classroom_session_id),
            self.session_store.session_pairings(classroom_session_id),
            self.template_store.list_rotations(classroom_session_id),
        )

    @staticmethod
    def _targets_for_assignment(
        assignment: PositionAssignment, classroom_session_id: str
    ) -> tuple[DeploymentTarget, ...]:
        if assignment.target is AssignmentTarget.ALL:
            return (DeploymentTarget("all", classroom_session_id),)
        if assignment.target is AssignmentTarget.GROUP:
            assert assignment.group_id is not None
            return (DeploymentTarget("group", assignment.group_id),)
        return tuple(
            DeploymentTarget("participant", participant_id)
            for participant_id in assignment.participant_ids
        )

    def _validate_plan_fens(self, plan: LessonPlan) -> None:
        for position in plan.positions:
            self._validate_fen(position.fen, f"lesson position {position.position_id}")

    def _validate_pairing_fens(self, pairings: Iterable[ClassroomPairing]) -> None:
        for pairing in pairings:
            if pairing.start_fen is not None:
                self._validate_fen(pairing.start_fen, f"pairing {pairing.pairing_id}")

    def _validate_fen(self, fen: str, context: str) -> None:
        try:
            self._fen_validator(fen)
        except Exception as exc:
            raise ValueError(f"Core rejected FEN for {context}: {exc}") from exc
