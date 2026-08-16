from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .teaching_ui import TeachingUiState


class TeachingAccessibleChessAPI:
    """Isolated feature-lane API for teaching controls.

    This is intentionally separate from the frozen release-facing launcher.
    It exposes presentation-only teaching state and never owns chess legality.
    """

    def __init__(self, state: TeachingUiState | None = None) -> None:
        self.teaching = state or TeachingUiState()

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


def main() -> None:
    import webview

    html = Path(__file__).resolve().parents[1] / "web" / "teaching.html"
    if not html.exists():
        raise RuntimeError(f"Teaching UI not found: {html}")
    webview.create_window(
        "Accessible Chess — Teaching Lab",
        url=str(html),
        js_api=TeachingAccessibleChessAPI(),
        width=1180,
        height=840,
        min_size=(820, 620),
        text_select=True,
    )
    webview.start(gui="edgechromium", private_mode=True)


if __name__ == "__main__":
    main()
