from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .child_coaching_ui import ChildCoachingPresentationState
from .classroom_collaboration_storage import AttachmentMetadata, ChatMessageMetadata
from .classroom_presentation import ClassroomPresentationState
from .lesson_application_service import LessonApplicationService
from .lesson_session_storage import LessonSessionSQLiteStore
from .lesson_storage import LessonSQLiteStore
from .lesson_template_presentation import LessonTemplatePresentation
from .lesson_template_storage import LessonTemplateSQLiteStore
from .local_profile import LocalProfileStore
from .position_editor import PositionState
from .teaching_action_presentation import TeachingActionPresentation
from .teaching_ui import TeachingUiState
from .visual_pack_presentation import VisualPackCatalogPresentation


class TeachingAccessibleChessAPI:
    """Isolated feature-lane API for teaching controls.

    This is intentionally separate from the frozen release-facing launcher.
    It exposes presentation-only teaching/classroom state and never owns chess
    legality, realtime transport, media bytes, or file execution.
    """

    def __init__(
        self,
        state: TeachingUiState | None = None,
        collaboration: ClassroomPresentationState | None = None,
        coaching: ChildCoachingPresentationState | None = None,
        visual_packs: VisualPackCatalogPresentation | None = None,
        lesson_templates: LessonTemplatePresentation | None = None,
        teaching_actions: TeachingActionPresentation | None = None,
    ) -> None:
        self.teaching = state or TeachingUiState()
        self.collaboration = collaboration or ClassroomPresentationState()
        self.coaching = coaching or ChildCoachingPresentationState()
        self.visual_packs = visual_packs or VisualPackCatalogPresentation()
        self.lesson_templates = lesson_templates
        self.teaching_actions = teaching_actions or TeachingActionPresentation(self.teaching)

    def teaching_snapshot(self) -> dict[str, Any]:
        return self.teaching.snapshot()

    def teaching_set_visual_preferences(self, payload: Mapping[str, object]) -> dict[str, Any]:
        return self.teaching.set_visual_preferences(payload)

    def teaching_pointer_commit(self, value: str) -> dict[str, Any]:
        return self.teaching.commit_pointer(value)

    def teaching_pointer_clear(self) -> dict[str, Any]:
        return self.teaching.clear_pointer()

    def teaching_record_student_pointer(
        self,
        participant_id: str,
        display_name: str,
        square: str,
        action: str = "point",
    ) -> dict[str, Any]:
        return self.teaching.record_student_pointer(participant_id, display_name, square, action)

    def teaching_add_square_annotation(self, annotation_id: str, square: str, style_id: str = "primary") -> dict[str, Any]:
        return self.teaching.add_square_annotation(annotation_id, square, style_id)

    def teaching_add_arrow_annotation(
        self,
        annotation_id: str,
        source: str,
        target: str,
        style_id: str = "primary",
    ) -> dict[str, Any]:
        return self.teaching.add_arrow_annotation(annotation_id, source, target, style_id)

    def teaching_remove_annotation(self, annotation_id: str) -> dict[str, Any]:
        return self.teaching.remove_annotation(annotation_id)

    def teaching_action_snapshot(self) -> dict[str, Any]:
        return self.teaching_actions.snapshot()

    def teaching_action_set_binding(self, action_id: str, binding: str | None) -> dict[str, Any]:
        return self.teaching_actions.set_binding(action_id, binding)

    def teaching_action_dispatch(
        self,
        action_id: str,
        payload: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        return self.teaching_actions.dispatch(action_id, payload)

    def teaching_action_dispatch_binding(
        self,
        binding: str,
        payload: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        return self.teaching_actions.dispatch_binding(binding, payload)

    def teaching_set_sound_master(self, enabled: bool, volume_percent: int) -> dict[str, Any]:
        return self.teaching.set_sound_master(enabled, volume_percent)

    def teaching_set_sound_event(
        self,
        event_id: str,
        enabled: bool | None = None,
        volume_percent: int | None = None,
        sound_id: str | None = None,
    ) -> dict[str, Any]:
        return self.teaching.set_sound_event(
            event_id,
            enabled=enabled,
            volume_percent=volume_percent,
            sound_id=sound_id,
        )

    def teaching_preview_sound_event(self, event_id: str) -> dict[str, Any]:
        return self.teaching.preview_sound_event(event_id)

    def teaching_coordinate_labels_for(self, square: str) -> dict[str, bool]:
        return self.teaching.coordinate_labels_for(square)

    def visual_pack_snapshot(self) -> dict[str, object]:
        return self.visual_packs.snapshot()

    def visual_pack_install(self, pack_id: str) -> dict[str, object]:
        return self.visual_packs.install(pack_id)

    def visual_pack_update(self, pack_id: str) -> dict[str, object]:
        return self.visual_packs.update(pack_id)

    def visual_pack_uninstall(self, pack_id: str) -> dict[str, object]:
        return self.visual_packs.uninstall(pack_id)

    def coaching_snapshot(self) -> dict[str, Any]:
        return self.coaching.snapshot()

    def coaching_select_template(self, template_id: str) -> dict[str, Any]:
        return self.coaching.select_template(template_id)

    def coaching_edit_template_block(
        self,
        block_id: str,
        title: str | None = None,
        duration_minutes: int | None = None,
    ) -> dict[str, Any]:
        return self.coaching.edit_template_block(
            block_id,
            title=title,
            duration_minutes=duration_minutes,
        )

    def coaching_template_prepare(self) -> dict[str, Any]:
        if self.lesson_templates is None:
            return self._template_unavailable()
        return self.lesson_templates.ensure_presets()

    def coaching_template_snapshot(self) -> dict[str, Any]:
        if self.lesson_templates is None:
            return self._template_unavailable()
        return self.lesson_templates.snapshot()

    def coaching_template_open(self, template_id: str) -> dict[str, Any]:
        if self.lesson_templates is None:
            return self._template_unavailable()
        return self.lesson_templates.open_template(template_id)

    def coaching_template_begin_copy(
        self,
        template_id: str,
        title: str,
        level: str | None = None,
    ) -> dict[str, Any]:
        if self.lesson_templates is None:
            return self._template_unavailable()
        return self.lesson_templates.begin_copy_current(
            template_id=template_id,
            title=title,
            level=level,
        )

    def coaching_template_edit_block(
        self,
        block_id: str,
        title: str | None = None,
        duration_minutes: int | None = None,
    ) -> dict[str, Any]:
        if self.lesson_templates is None:
            return self._template_unavailable()
        return self.lesson_templates.edit_block(
            block_id,
            title=title,
            duration_minutes=duration_minutes,
        )

    def coaching_template_save(self) -> dict[str, Any]:
        if self.lesson_templates is None:
            return self._template_unavailable()
        return self.lesson_templates.save()

    def coaching_previous_position(self) -> dict[str, Any]:
        return self.coaching.previous_position()

    def coaching_next_position(self) -> dict[str, Any]:
        return self.coaching.next_position()

    def coaching_deploy_position(
        self,
        target: str = "all",
        participant_ids: list[str] | None = None,
        group_id: str | None = None,
    ) -> dict[str, Any]:
        return self.coaching.deploy_selected(
            target,
            participant_ids=tuple(participant_ids or ()),
            group_id=group_id,
        )

    def coaching_pointer_answer(self, display_name: str, square: str) -> dict[str, Any]:
        return self.coaching.pointer_only_answer(display_name, square)

    def coaching_start_rotation(
        self,
        participant_ids: list[str],
        mode: str = "sequential",
        base_seconds: int = 600,
        increment_seconds: int = 0,
    ) -> dict[str, Any]:
        return self.coaching.start_rotation(
            participant_ids,
            mode=mode,
            base_seconds=base_seconds,
            increment_seconds=increment_seconds,
        )

    def coaching_previous_board(self) -> dict[str, Any]:
        return self.coaching.previous_board()

    def coaching_next_board(self) -> dict[str, Any]:
        return self.coaching.next_board()

    def coaching_next_rotation_round(self) -> dict[str, Any]:
        return self.coaching.next_rotation_round()

    def coaching_return_demo(self) -> dict[str, Any]:
        return self.coaching.return_to_demonstration()

    def coaching_dispatch(self, action_id: str, payload: Mapping[str, object] | None = None) -> dict[str, Any]:
        return self.coaching.dispatch(action_id, payload)

    def coaching_dispatch_binding(self, binding: str, payload: Mapping[str, object] | None = None) -> dict[str, Any]:
        return self.coaching.dispatch_binding(binding, payload)

    def classroom_snapshot(self) -> dict[str, Any]:
        return self.collaboration.snapshot()

    def classroom_profile_ensure(self) -> dict[str, Any]:
        return self.collaboration.ensure_profile()

    def classroom_profile_set_display_name(self, value: str | None) -> dict[str, Any]:
        return self.collaboration.set_display_name(value)

    def classroom_chat_mark_read(self) -> dict[str, Any]:
        return self.collaboration.mark_chat_read()

    def classroom_receive_chat(
        self,
        message_id: str,
        room_id: str,
        sender_id: str,
        sequence_no: int,
        sender_display_name: str,
        body: str,
    ) -> dict[str, Any]:
        message = ChatMessageMetadata(
            str(message_id),
            str(room_id),
            str(sender_id),
            int(sequence_no),
            str(body),
        )
        return self.collaboration.append_message(
            message,
            sender_display_name=sender_display_name,
            incoming=True,
        )

    def classroom_receive_attachment(
        self,
        attachment_id: str,
        room_id: str,
        sender_id: str,
        sequence_no: int,
        sender_display_name: str,
        display_name: str,
        size_bytes: int,
        mime_type: str | None,
        sha256: str,
        object_key: str,
        transfer_state: str,
        scan_state: str,
    ) -> dict[str, Any]:
        item = AttachmentMetadata(
            str(attachment_id),
            str(room_id),
            str(sender_id),
            int(sequence_no),
            str(display_name),
            None if mime_type is None else str(mime_type),
            int(size_bytes),
            str(sha256),
            str(object_key),
            str(transfer_state),
            "session",
            str(scan_state),
        )
        return self.collaboration.register_attachment(
            item,
            sender_display_name=sender_display_name,
        )

    @staticmethod
    def _template_unavailable() -> dict[str, Any]:
        return {
            "ok": False,
            "open": False,
            "template": None,
            "accessibleText": "Збережені шаблони уроків недоступні.",
        }


def _default_collaboration_state() -> ClassroomPresentationState:
    data_dir = Path.home() / ".accessible_chess"
    profile_store = LocalProfileStore(data_dir / "teaching_profile.json")
    return ClassroomPresentationState(profile_store=profile_store)


def _validate_lesson_fen(fen: str) -> None:
    position = PositionState.from_fen(fen)
    problems = position.validate_playable()
    if problems:
        raise ValueError("position is not playable")


def _default_lesson_template_presentation() -> LessonTemplatePresentation:
    data_dir = Path.home() / ".accessible_chess"
    db_path = data_dir / "teaching_lessons.sqlite3"
    application = LessonApplicationService(
        lesson_store=LessonSQLiteStore(db_path, fen_validator=_validate_lesson_fen),
        template_store=LessonTemplateSQLiteStore(db_path),
        session_store=LessonSessionSQLiteStore(db_path, fen_validator=_validate_lesson_fen),
        fen_validator=_validate_lesson_fen,
    )
    return LessonTemplatePresentation(application)


def main() -> None:
    import webview

    html = Path(__file__).resolve().parents[1] / "web" / "teaching.html"
    if not html.exists():
        raise RuntimeError(f"Teaching UI not found: {html}")
    window = webview.create_window(
        "Accessible Chess — Teaching Lab",
        url=str(html),
        js_api=TeachingAccessibleChessAPI(
            collaboration=_default_collaboration_state(),
            lesson_templates=_default_lesson_template_presentation(),
        ),
        width=1180,
        height=840,
        min_size=(820, 620),
        text_select=True,
    )

    def add_teaching_links() -> None:
        window.evaluate_js(
            """
            if (document.title.includes('Teaching Lab')) {
              const header = document.querySelector('header');
              if (!header) return;
              if (!document.getElementById('child-coaching-link')) {
                const link = document.createElement('a');
                link.id = 'child-coaching-link';
                link.href = 'child_coaching.html';
                link.textContent = 'План уроку й робота з групою';
                header.append(' — ', link);
              }
              if (!document.getElementById('visual-packs-link')) {
                const link = document.createElement('a');
                link.id = 'visual-packs-link';
                link.href = 'visual_packs.html';
                link.textContent = 'Пакети оформлення';
                header.append(' — ', link);
              }
              if (!document.getElementById('teaching-actions-link')) {
                const link = document.createElement('a');
                link.id = 'teaching-actions-link';
                link.href = 'teaching_actions.html';
                link.textContent = 'Команди й клавіші';
                header.append(' — ', link);
              }
            }
            """
        )

    window.events.loaded += add_teaching_links
    webview.start(gui="edgechromium", private_mode=True)


if __name__ == "__main__":
    main()
