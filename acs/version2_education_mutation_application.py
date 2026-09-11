from __future__ import annotations

"""First bounded Education mutation composed into the final-product V2 app."""

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


class MutableEducationWebViewProjection(EducationWebViewProjection):
    """Keep the existing read projection and refresh after trusted class creation."""

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


class Version2EducationMutationApplication(Version2FinalProductApplication):
    """Final-product application with one durable, keyboard-reachable D10 mutation.

    The browser can request ``classes.new`` but cannot provide the canonical
    class identity, operation identity, workspace revision, or storage path.
    Those remain trusted-host state and publication stays on the existing D10
    ``EducationWorkspaceStore`` CAS boundary.
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
