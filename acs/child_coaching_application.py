from __future__ import annotations

"""Application boundary for accessible child-coaching template workflows.

The service composes the child-coaching domain with its durable CAS store. It
owns no chess state and does not bypass the canonical TeachingSession compiler.
WebView/native presentation can bind to this service after the active Teacher UI
owner converges its current changes.
"""

from dataclasses import dataclass, replace

from .child_coaching import (
    AgeBand,
    ChildCoachingError,
    LessonBlock,
    LessonLevel,
    LessonTemplate,
    compile_lesson_session,
    copy_as_custom,
    ensure_preset_templates,
)
from .child_coaching_store import (
    ChildCoachingStoreConflictError,
    ChildCoachingTemplateStore,
    LoadedChildCoachingTemplates,
)
from .teaching_session import LessonSession, TeachingPositionSource


class ChildCoachingApplicationError(ValueError):
    """Stable user-facing application error for template workflows."""


@dataclass(frozen=True, slots=True)
class TemplateSummary:
    template_id: str
    title: str
    age_band: AgeBand
    level: LessonLevel
    total_minutes: int
    block_count: int
    no_notation_required: bool
    custom: bool

    @property
    def accessible_text(self) -> str:
        notation = "no notation required" if self.no_notation_required else "notation used"
        kind = "custom" if self.custom else "preset"
        return (
            f"{self.title}, {self.age_band.value}, {self.level.value}, "
            f"{self.total_minutes} minutes, {self.block_count} blocks, "
            f"{notation}, {kind}"
        )


@dataclass(frozen=True, slots=True)
class TemplateCatalogSnapshot:
    revision: str
    templates: tuple[TemplateSummary, ...]
    recovered_from_backup: bool = False

    def summary(self, template_id: str) -> TemplateSummary:
        for item in self.templates:
            if item.template_id == template_id:
                return item
        raise ChildCoachingApplicationError("lesson template does not exist")


class ChildCoachingApplication:
    """Revision-aware application service over one durable template catalog."""

    def __init__(self, store: ChildCoachingTemplateStore) -> None:
        if type(store) is not ChildCoachingTemplateStore:
            raise TypeError("store must be ChildCoachingTemplateStore")
        self.store = store

    def open_catalog(self) -> TemplateCatalogSnapshot:
        loaded = self._load_or_seed()
        seeded = ensure_preset_templates(loaded.templates)
        if seeded != loaded.templates:
            try:
                revision = self.store.save(
                    seeded,
                    expected_revision=loaded.revision,
                )
            except ChildCoachingStoreConflictError:
                loaded = self._require_loaded()
            else:
                loaded = LoadedChildCoachingTemplates(
                    templates=tuple(sorted(seeded, key=lambda item: item.template_id)),
                    revision=revision,
                    recovered_from_backup=False,
                )
        return self._snapshot(loaded)

    def get_template(self, template_id: str) -> tuple[LessonTemplate, str]:
        loaded = self._load_or_seed()
        return self._find(loaded.templates, template_id), loaded.revision

    def copy_template(
        self,
        source_template_id: str,
        *,
        template_id: str,
        title: str,
        expected_revision: str,
    ) -> TemplateCatalogSnapshot:
        loaded = self._require_revision(expected_revision)
        source = self._find(loaded.templates, source_template_id)
        if any(item.template_id == template_id for item in loaded.templates):
            raise ChildCoachingApplicationError("lesson template id already exists")
        try:
            copied = copy_as_custom(source, template_id=template_id, title=title)
        except ChildCoachingError as exc:
            raise ChildCoachingApplicationError("invalid lesson template copy") from exc
        return self._publish(loaded, loaded.templates + (copied,))

    def replace_block(
        self,
        template_id: str,
        block_id: str,
        replacement: LessonBlock,
        *,
        expected_revision: str,
    ) -> TemplateCatalogSnapshot:
        loaded = self._require_revision(expected_revision)
        template = self._find(loaded.templates, template_id)
        try:
            changed = template.replace_block(block_id, replacement)
        except ChildCoachingError as exc:
            raise ChildCoachingApplicationError("lesson block update was rejected") from exc
        templates = tuple(
            changed if item.template_id == template_id else item
            for item in loaded.templates
        )
        return self._publish(loaded, templates)

    def rename_template(
        self,
        template_id: str,
        title: str,
        *,
        expected_revision: str,
    ) -> TemplateCatalogSnapshot:
        loaded = self._require_revision(expected_revision)
        template = self._find(loaded.templates, template_id)
        try:
            changed = replace(template, title=title, custom=True)
        except ChildCoachingError as exc:
            raise ChildCoachingApplicationError("lesson template rename was rejected") from exc
        templates = tuple(
            changed if item.template_id == template_id else item
            for item in loaded.templates
        )
        return self._publish(loaded, templates)

    def delete_custom_template(
        self,
        template_id: str,
        *,
        expected_revision: str,
    ) -> TemplateCatalogSnapshot:
        loaded = self._require_revision(expected_revision)
        template = self._find(loaded.templates, template_id)
        if not template.custom:
            raise ChildCoachingApplicationError(
                "built-in lesson preset cannot be deleted"
            )
        templates = tuple(
            item for item in loaded.templates
            if item.template_id != template_id
        )
        return self._publish(loaded, templates)

    def compile_session(
        self,
        template_id: str,
        *,
        session_id: str,
        lesson_id: str,
        source: TeachingPositionSource,
        student_ids: tuple[str, ...] = (),
        cohort_id: str | None = None,
        require_no_notation: bool = False,
        expected_revision: str | None = None,
    ) -> LessonSession:
        loaded = (
            self._load_or_seed()
            if expected_revision is None
            else self._require_revision(expected_revision)
        )
        template = self._find(loaded.templates, template_id)
        try:
            return compile_lesson_session(
                template,
                session_id=session_id,
                lesson_id=lesson_id,
                source=source,
                student_ids=student_ids,
                cohort_id=cohort_id,
                require_no_notation=require_no_notation,
            )
        except ChildCoachingError as exc:
            raise ChildCoachingApplicationError(
                "lesson template cannot start this session"
            ) from exc

    def _load_or_seed(self) -> LoadedChildCoachingTemplates:
        loaded = self.store.load()
        if loaded is not None:
            return loaded
        presets = ensure_preset_templates(())
        try:
            revision = self.store.save(presets, expected_revision=None)
        except ChildCoachingStoreConflictError:
            return self._require_loaded()
        return LoadedChildCoachingTemplates(
            templates=tuple(sorted(presets, key=lambda item: item.template_id)),
            revision=revision,
        )

    def _require_loaded(self) -> LoadedChildCoachingTemplates:
        loaded = self.store.load()
        if loaded is None:
            raise ChildCoachingApplicationError("lesson template catalog is unavailable")
        return loaded

    def _require_revision(self, expected_revision: str) -> LoadedChildCoachingTemplates:
        loaded = self._load_or_seed()
        if loaded.revision != expected_revision:
            raise ChildCoachingApplicationError(
                "lesson templates changed; reopen them before saving"
            )
        return loaded

    def _publish(
        self,
        loaded: LoadedChildCoachingTemplates,
        templates: tuple[LessonTemplate, ...],
    ) -> TemplateCatalogSnapshot:
        try:
            revision = self.store.save(
                templates,
                expected_revision=loaded.revision,
            )
        except ChildCoachingStoreConflictError as exc:
            raise ChildCoachingApplicationError(
                "lesson templates changed; reopen them before saving"
            ) from exc
        published = LoadedChildCoachingTemplates(
            templates=tuple(sorted(templates, key=lambda item: item.template_id)),
            revision=revision,
        )
        return self._snapshot(published)

    @staticmethod
    def _find(
        templates: tuple[LessonTemplate, ...],
        template_id: str,
    ) -> LessonTemplate:
        for item in templates:
            if item.template_id == template_id:
                return item
        raise ChildCoachingApplicationError("lesson template does not exist")

    @staticmethod
    def _snapshot(loaded: LoadedChildCoachingTemplates) -> TemplateCatalogSnapshot:
        return TemplateCatalogSnapshot(
            revision=loaded.revision,
            templates=tuple(
                TemplateSummary(
                    template_id=item.template_id,
                    title=item.title,
                    age_band=item.age_band,
                    level=item.level,
                    total_minutes=item.total_minutes,
                    block_count=len(item.blocks),
                    no_notation_required=item.no_notation_required,
                    custom=item.custom,
                )
                for item in loaded.templates
            ),
            recovered_from_backup=loaded.recovered_from_backup,
        )
