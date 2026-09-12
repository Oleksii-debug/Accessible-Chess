from __future__ import annotations

"""Bounded Education mutation and read-open composition for the final-product V2 app."""

from collections.abc import Mapping
import secrets

from .education_class_management import create_class
from .education_webview_bridge import EducationWebViewBridge
from .education_webview_projection import (
    EducationCollection,
    EducationWebViewEvent,
    EducationWebViewProjection,
)
from .full_product_ui_shell import UILanguage
from .version2_final_product_application import Version2FinalProductApplication


_CREATED = {
    UILanguage.UA: "Клас створено",
    UILanguage.EN: "Class created",
}
_DEFAULT_TITLE = {
    UILanguage.UA: "Новий клас",
    UILanguage.EN: "New class",
}
_OPENED = {
    UILanguage.UA: "Відкрито",
    UILanguage.EN: "Opened",
}
_OPEN_ACTIONS = {
    EducationCollection.CLASS: "classes.open",
    EducationCollection.STUDENT: "classes.student_open",
    EducationCollection.LESSON: "classes.lesson_open",
    EducationCollection.ASSIGNMENT: "classes.assignment_open",
}
_OPEN_RECORDS = {
    "classes.open": ("classes", "class_id", EducationCollection.CLASS.value),
    "classes.student_open": ("students", "student_id", EducationCollection.STUDENT.value),
    "classes.lesson_open": ("lessons", "lesson_id", EducationCollection.LESSON.value),
    "classes.assignment_open": (
        "assignments",
        "assignment_id",
        EducationCollection.ASSIGNMENT.value,
    ),
}


class MutableEducationWebViewProjection(EducationWebViewProjection):
    """Keep the canonical projection and add trusted class-create/read-open events."""

    def new_class(self) -> EducationWebViewEvent:
        try:
            result = self._dispatch("classes.new", {})
            if not isinstance(result, Mapping):
                raise TypeError("class creation result must be a mapping")
            class_id = result.get("class_id")
            if type(class_id) is not str or not class_id:
                raise ValueError("class creation result is missing class identity")

            records = self._records(self._workspace())[EducationCollection.CLASS]
            index = next(
                index
                for index, record in enumerate(records)
                if record.record_id == class_id
            )
            self._pages[EducationCollection.CLASS] = index // self._page_size
            self._selected[EducationCollection.CLASS] = class_id
            updated = self._section(EducationCollection.CLASS, records)
        except Exception as exc:
            return self._safe_error(exc)

        return EducationWebViewEvent(
            "selection",
            {
                "snapshot": updated,
                "focus_target": updated["focus_target"],
                "announcement": _CREATED[self._language],
            },
        )

    def open_selected(self, kind: EducationCollection | str) -> EducationWebViewEvent:
        """Publish a bounded read-only detail after trusted-host revalidation."""

        try:
            parsed = self._parse_kind(kind)
            action = _OPEN_ACTIONS[parsed]
            records = self._records(self._workspace())[parsed]
            selected_id = self._selected[parsed]
            selected = next(
                record for record in records if record.record_id == selected_id
            )

            # Browser content never supplies this identity. It is recovered from
            # the HMAC-backed selection and revalidated by the trusted host.
            self._dispatch(action, {"record_id": selected_id})
            detail = {
                "kind": parsed.value,
                "heading": self._bounded(selected.label, limit=160),
                "secondary": self._bounded(selected.secondary, limit=200),
                "status": self._bounded(selected.status, limit=160),
            }
        except Exception as exc:
            return self._safe_error(exc)

        return EducationWebViewEvent(
            "delegated",
            {
                "kind": parsed.value,
                "action": action,
                "detail": detail,
                "focus_target": "education-detail-heading",
                "announcement": f"{_OPENED[self._language]}: {detail['heading']}",
            },
        )


class Version2EducationMutationApplication(Version2FinalProductApplication):
    """Final-product Education composition over the canonical D10 workspace.

    The browser can request ``classes.new`` but cannot provide the canonical
    class identity, operation identity, workspace revision, or storage path.
    Open-selected actions receive a record identity only from the trusted
    HMAC-backed projection, validate it against the current canonical workspace,
    and return no durable mutation or raw identity to browser content.
    """

    @staticmethod
    def _class_id(workspace) -> str:
        existing = {item.class_id for item in workspace.classroom.classes}
        for _ in range(32):
            candidate = f"class-{secrets.token_hex(16)}"
            if candidate not in existing:
                return candidate
        raise RuntimeError("could not allocate a unique class identity")

    def _education_dispatch(
        self,
        action_id: str,
        payload: Mapping[str, object],
    ) -> object:
        open_spec = _OPEN_RECORDS.get(action_id)
        if open_spec is not None:
            if set(payload) != {"record_id"}:
                raise ValueError("education open accepts only trusted record identity")
            record_id = payload.get("record_id")
            if type(record_id) is not str or not record_id:
                raise ValueError("education open requires a non-empty record identity")

            workspace = self._education_provider()
            collection_name, identity_name, kind = open_spec
            records = getattr(workspace.classroom, collection_name)
            matches = sum(
                1 for record in records
                if getattr(record, identity_name) == record_id
            )
            if matches != 1:
                raise LookupError("selected education record is no longer current")
            return {"validated": True, "kind": kind}

        if action_id != "classes.new":
            return super()._education_dispatch(action_id, payload)
        if payload:
            raise ValueError("new class does not accept browser-supplied identity fields")

        workspace = self._education_provider()
        class_id = self._class_id(workspace)
        operation_id = f"class-create-{secrets.token_hex(16)}"
        ordinal = len(workspace.classroom.classes) + 1
        title = f"{_DEFAULT_TITLE[self.shell.language]} {ordinal}"
        updated = create_class(
            workspace,
            class_id=class_id,
            title=title,
            operation_id=operation_id,
        )
        revision = self.replace_education_workspace(
            updated,
            expected_revision=self.education_revision,
        )
        return {"class_id": class_id, "revision": revision}

    def _rebuild_education_bridge(self, language: UILanguage) -> None:
        if self._education_workspace is None:
            self.education = None
            return
        projection = MutableEducationWebViewProjection(
            self._education_provider,
            self._education_dispatch,
            language=language,
        )
        self.education = EducationWebViewBridge(projection)


__all__ = [
    "MutableEducationWebViewProjection",
    "Version2EducationMutationApplication",
]
