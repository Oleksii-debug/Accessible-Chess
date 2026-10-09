from __future__ import annotations

"""Persistent UI-facing service for the central Accessible Chess action registry.

The WebView must not own shortcut normalization, conflict policy, profile migration,
or persistence. This facade is deliberately JSON-friendly so pywebview can expose
it without leaking filesystem or registry internals into JavaScript.
"""

import json
from pathlib import Path
from typing import Any, Mapping

from .keybindings import (
    ActionRegistry, BindingContext, KeymapProfileConflictError, SCHEMA_VERSION, normalize_binding,
)
from .ui_keymap_adapter import build_web_keymap
from .ui_keymap_editor import KeymapEditorModel


_MODIFIER_KEYS = frozenset({"Control", "Ctrl", "Alt", "Shift", "Meta", "Win", "Windows"})
_KEY_ALIASES = {
    " ": "Space",
    "Spacebar": "Space",
    "Esc": "Escape",
    "Return": "Enter",
    "Del": "Delete",
    "ArrowLeft": "Left",
    "ArrowRight": "Right",
    "ArrowUp": "Up",
    "ArrowDown": "Down",
    "PageUp": "PageUp",
    "PageDown": "PageDown",
    "+": "Plus",
    "-": "Minus",
}

MAX_KEYMAP_PROFILE_BYTES = 1 << 20
MAX_KEYMAP_OBJECT_ENTRIES = 4096


def _reject_duplicate_object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    if len(pairs) > MAX_KEYMAP_OBJECT_ENTRIES:
        raise ValueError("keymap profile object is too large")
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate keymap profile key: {key}")
        value[key] = item
    return value


def _bounded_user_keymap_text(text: str) -> str:
    # Reject active str subclasses before len()/encode() can execute user hooks.
    if type(text) is not str:
        raise ValueError("keymap profile must be text")
    if len(text) > MAX_KEYMAP_PROFILE_BYTES:
        raise ValueError("keymap profile is too large")
    try:
        encoded = text.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ValueError("keymap profile must be valid UTF-8 text") from exc
    if len(encoded) > MAX_KEYMAP_PROFILE_BYTES:
        raise ValueError("keymap profile is too large")
    return text


def _decode_user_keymap_profile(text: str) -> Mapping[str, object]:
    """Validate one bounded, unambiguous user-facing keymap envelope.

    ``ActionRegistry`` retains bounded legacy migration for internal callers.
    The WebView/user-file boundary is stricter: text must be passive built-in
    Unicode within the same byte envelope for direct import and disk recovery;
    JSON objects cannot contain duplicate keys; and an explicit schema version
    must be a real JSON integer (not bool/float/numeric text).
    """

    text = _bounded_user_keymap_text(text)
    try:
        value = json.loads(text, object_pairs_hook=_reject_duplicate_object_pairs)
    except RecursionError as exc:
        raise ValueError("keymap profile nesting is too deep") from exc
    if not isinstance(value, Mapping):
        raise ValueError("keymap profile must be a JSON object")
    if "schema_version" in value:
        version = value["schema_version"]
        if isinstance(version, bool) or not isinstance(version, int) or version < 0:
            raise ValueError("invalid keymap schema_version")
    for current, legacy in (("bindings", "keys"), ("aliases", "commands")):
        if current in value:
            container = value[current]
        elif "schema_version" not in value and legacy in value:
            container = value[legacy]
        else:
            continue
        if not isinstance(container, Mapping):
            raise ValueError("invalid keymap profile")
    return value


def _read_user_keymap_profile(path: Path) -> Mapping[str, object]:
    # Do not use read_text()/read_bytes(): both allocate an unbounded file before
    # the user-profile boundary gets a chance to reject it.
    with path.open("rb") as stream:
        payload = stream.read(MAX_KEYMAP_PROFILE_BYTES + 1)
    if len(payload) > MAX_KEYMAP_PROFILE_BYTES:
        raise ValueError("keymap profile is too large")
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError("keymap profile must be valid UTF-8 text") from exc
    return _decode_user_keymap_profile(text)


def _invalid_profile_response(lang: str) -> dict[str, Any]:
    return {
        "ok": False,
        "message": "Invalid keyboard profile." if lang == "en" else "Некоректний профіль клавіш.",
        "conflicts": [],
        "requiresConfirmation": False,
    }


class KeymapService:
    def __init__(self, path: str | Path, *, lang: str = "uk") -> None:
        self.path = Path(path)
        recovery = None
        self._profile_write_blocked = False
        if self.path.exists():
            try:
                profile = _read_user_keymap_profile(self.path)
                version = profile.get("schema_version", 0)
                self._profile_write_blocked = type(version) is int and version > SCHEMA_VERSION
                registry = ActionRegistry.from_profile(profile)
            except OSError:
                # An existing profile that cannot currently be read is not the
                # same thing as malformed content. Preserve its bytes and fail
                # closed against incremental writes so a transient sharing,
                # permission, device, or filesystem error cannot replace the
                # user's keymap with defaults.
                registry = ActionRegistry()
                self._profile_write_blocked = True
                recovery = "unreadable keymap profile"
            except Exception:
                registry = ActionRegistry()
                recovery = (
                    "newer keymap profile"
                    if self._profile_write_blocked
                    else "invalid keymap profile"
                )
                # Any existing profile that cannot be validated remains the
                # persisted authority until the user explicitly chooses Reset all
                # or imports a replacement. Defaults may be used in memory for
                # recovery, but an ordinary incremental edit must not destroy the
                # malformed/newer source bytes.
                self._profile_write_blocked = True
        else:
            registry = ActionRegistry()
        self.editor = KeymapEditorModel(registry, lang=lang)
        self.recovery_message = recovery

    def snapshot(self) -> dict[str, Any]:
        data = build_web_keymap(self.editor.registry)
        data["recoveryMessage"] = self.recovery_message
        data["writeBlocked"] = self._profile_write_blocked
        data["maxImportBytes"] = MAX_KEYMAP_PROFILE_BYTES
        return data

    def adopt_registry(self, registry: ActionRegistry) -> ActionRegistry:
        """Adopt a wider registry without dropping persisted non-Stage1 actions.

        The Stage1 API is constructed before the Version 2 application. A saved
        full-product profile therefore passes through an initially narrower
        registry whose constructor intentionally ignores unknown action IDs.
        Re-read the already validated persisted envelope when it is usable, then
        validate the whole profile against the wider definition set before
        replacing live values. This preserves full-product remaps across restart
        and also supports valid binding swaps without transient replay conflicts.
        """

        if not isinstance(registry, ActionRegistry):
            raise TypeError("registry must be ActionRegistry")

        source_profile = self.editor.registry.to_profile()
        profile: Mapping[str, object] = source_profile

        if (
            self.path.exists()
            and self.recovery_message is None
            and not self._profile_write_blocked
        ):
            try:
                profile = _read_user_keymap_profile(self.path)
            except OSError:
                # The file was readable at initial boot but became unavailable
                # before Product registry adoption. Do not let the wider default
                # registry become new persisted authority while the original file
                # is unreadable.
                profile = source_profile
                self._profile_write_blocked = True
                self.recovery_message = "unreadable keymap profile"
            except Exception:
                # The file changed into malformed/unsupported content between
                # initial boot and wider Product adoption. Keep the already-loaded
                # values usable in memory but protect the changed file from later
                # incremental overwrite until explicit recovery.
                profile = source_profile
                self._profile_write_blocked = True
                self.recovery_message = "invalid keymap profile"

        merged = registry.to_profile()
        try:
            version = profile.get("schema_version", 0)
            if version == 0:
                # Match ActionRegistry's bounded legacy migration exactly. An
                # unversioned profile may use keys/commands, and an explicitly
                # empty current container still falls back to its legacy peer.
                profile_bindings = profile.get("bindings") or profile.get("keys") or {}
                profile_aliases = profile.get("aliases") or profile.get("commands") or {}
            else:
                profile_bindings = profile.get("bindings", {})
                profile_aliases = profile.get("aliases", {})
            if not isinstance(profile_bindings, Mapping) or not isinstance(profile_aliases, Mapping):
                raise ValueError("invalid keymap profile")
            merged_bindings = merged.get("bindings")
            merged_aliases = merged.get("aliases")
            if not isinstance(merged_bindings, dict) or not isinstance(merged_aliases, dict):
                raise ValueError("invalid wider registry profile")
            merged_bindings.update(profile_bindings)
            merged_aliases.update(profile_aliases)
            registry.replace_profile(merged)
        except Exception:
            # replace_profile validates before mutating, so a profile that only
            # becomes invalid under the wider Product definition set leaves the
            # application's existing wider registry untouched. Preserve the file
            # for explicit recovery instead of silently rewriting it at startup.
            self._profile_write_blocked = True
            self.recovery_message = "invalid keymap profile"

        self.editor.registry = registry
        return registry

    def search(self, query: str = "", context: str | None = None) -> list[dict[str, Any]]:
        parsed_context = BindingContext(context) if context else None
        return [row.__dict__.copy() for row in self.editor.rows(query=query, context=parsed_context)]

    def preview(self, action_id: str, value: str) -> dict[str, Any]:
        """Return live validation for a captured value without mutating state.

        This is the single WebView bridge for pre-save validation. JavaScript may
        render the returned status in an aria-live region, but normalization and
        conflict policy stay in the central registry/editor model.
        """

        preview = self.editor.preview(action_id, value)
        return {
            "actionId": preview.action_id,
            "value": preview.value,
            "valueKind": preview.value_kind,
            "canSave": preview.can_save,
            "requiresConfirmation": preview.requires_confirmation,
            "status": preview.status,
            "message": preview.message,
            "conflicts": [self._conflict(item) for item in preview.conflicts],
        }

    def capture_shortcut(
        self,
        action_id: str,
        key: str,
        *,
        ctrl: bool = False,
        alt: bool = False,
        shift: bool = False,
        win: bool = False,
    ) -> dict[str, Any]:
        """Convert one browser/native key event into a validated shortcut preview.

        The presentation sends only event facts. It does not normalize chords,
        decide conflicts, or persist anything. Tab remains native focus navigation,
        Escape cancels capture, and modifier-only events stay incomplete so a
        keyboard-only user cannot accidentally save an unusable binding.

        Browser KeyboardEvent.key represents the Space key as a literal single
        space in some WebView/Chromium versions. Preserve that exact value before
        trimming other key names, otherwise Space becomes an empty key and cannot
        be assigned by a keyboard-only user.
        """

        if not isinstance(key, str) or any(not isinstance(flag, bool) for flag in (ctrl, alt, shift, win)):
            return {
                "captured": False,
                "reason": "invalid",
                "binding": "",
                "status": "error",
                "message": "Invalid shortcut" if self.editor.lang == "en" else "Некоректна комбінація.",
                "canSave": False,
                "requiresConfirmation": False,
                "conflicts": [],
            }
        event_key = key
        raw_key = event_key if event_key == " " else event_key.strip()
        if raw_key == "Tab":
            return self._capture_control("navigation", "Tab")
        if raw_key in {"Escape", "Esc"}:
            return self._capture_control("cancelled", "Escape")
        if not raw_key or raw_key in _MODIFIER_KEYS:
            message = (
                "Press a non-modifier key to complete the shortcut."
                if self.editor.lang == "en"
                else "Натисніть клавішу, що не є модифікатором, щоб завершити комбінацію."
            )
            return {
                "captured": False,
                "reason": "incomplete",
                "binding": "",
                "status": "pending",
                "message": message,
                "canSave": False,
                "requiresConfirmation": False,
                "conflicts": [],
            }

        canonical_key = _KEY_ALIASES.get(raw_key, raw_key)
        parts: list[str] = []
        if ctrl:
            parts.append("Ctrl")
        if alt:
            parts.append("Alt")
        if shift:
            parts.append("Shift")
        if win:
            parts.append("Win")
        parts.append(canonical_key)

        try:
            binding = normalize_binding("+".join(parts)) or ""
        except ValueError as exc:
            return {
                "captured": False,
                "reason": "invalid",
                "binding": "",
                "status": "error",
                "message": str(exc),
                "canSave": False,
                "requiresConfirmation": False,
                "conflicts": [],
            }

        preview = self.preview(action_id, binding)
        return {
            "captured": True,
            "reason": "captured",
            "binding": binding,
            **preview,
        }

    def resolve_binding(self, context: str, binding: str) -> dict[str, Any] | None:
        """Resolve a live keyboard chord to its current action for WebView dispatch.

        The browser must not cache default shortcuts or reproduce context fallback
        rules. Every keydown can ask this bridge for the action that is active in
        the user's current persisted keymap, so remapping takes effect immediately.
        """

        resolution = self.editor.registry.resolve_binding(BindingContext(context), binding)
        return self._resolution(resolution)

    def resolve_alias(self, context: str, alias: str) -> dict[str, Any] | None:
        """Resolve a typed command alias through the current central registry.

        This keeps move-entry commands remappable without conflating command
        aliases with literal chess syntax such as W:/B: in the position editor.
        """

        resolution = self.editor.registry.resolve_alias(BindingContext(context), alias)
        return self._resolution(resolution)

    def save(self, action_id: str, value: str, *, allow_warnings: bool = False) -> dict[str, Any]:
        blocked = self._blocked_incremental_mutation()
        if blocked is not None:
            return blocked
        before_registry = self.editor.registry
        before_profile = before_registry.to_profile()
        result = self.editor.save(action_id, value, allow_warnings=allow_warnings)
        return self._commit_persisted_mutation(
            result,
            before_registry=before_registry,
            before_profile=before_profile,
        )

    def reset_action(self, action_id: str) -> dict[str, Any]:
        blocked = self._blocked_incremental_mutation()
        if blocked is not None:
            return blocked
        before_registry = self.editor.registry
        before_profile = before_registry.to_profile()
        result = self.editor.reset_action(action_id)
        return self._commit_persisted_mutation(
            result,
            before_registry=before_registry,
            before_profile=before_profile,
        )

    def reset_context(self, context: str) -> dict[str, Any]:
        blocked = self._blocked_incremental_mutation()
        if blocked is not None:
            return blocked
        before_registry = self.editor.registry
        before_profile = before_registry.to_profile()
        result = self.editor.reset_context(BindingContext(context))
        return self._commit_persisted_mutation(
            result,
            before_registry=before_registry,
            before_profile=before_profile,
        )

    def reset_all(self) -> dict[str, Any]:
        before_registry = self.editor.registry
        before_profile = before_registry.to_profile()
        result = self.editor.reset_all()
        return self._commit_persisted_mutation(
            result,
            before_registry=before_registry,
            before_profile=before_profile,
            replace_incompatible=True,
        )

    def export_profile(self) -> str:
        return self.editor.export_profile()

    def import_profile(self, text: str, *, allow_warnings: bool = False) -> dict[str, Any]:
        """Import a profile atomically and never silently accept risky shortcuts.

        A profile may be structurally valid while containing browser/WebView2,
        Windows, or likely NVDA shortcut warnings. Direct per-action editing already
        requires explicit confirmation for those values; profile import must not be
        a back door around the same safety policy. The first call therefore leaves
        the current registry and persisted file untouched and returns
        ``requiresConfirmation=True``. A UI may repeat the same import with
        ``allow_warnings=True`` only after announcing the warnings and receiving an
        explicit user confirmation.
        """

        if type(allow_warnings) is not bool:
            return _invalid_profile_response(self.editor.lang)

        try:
            profile = _decode_user_keymap_profile(text)
            candidate = ActionRegistry.from_profile(profile, self.editor.registry.definitions())
            conflicts = candidate.validate()
        except KeymapProfileConflictError as exc:
            blocking = tuple(item for item in exc.conflicts if item.severity == "error")
            return {
                "ok": False,
                "message": self.editor.conflict_summary(blocking),
                "conflicts": [self._conflict(item) for item in exc.conflicts],
                "requiresConfirmation": False,
            }
        except (ValueError, TypeError, AttributeError):
            return _invalid_profile_response(self.editor.lang)

        blocking = tuple(item for item in conflicts if item.severity == "error")
        warnings = tuple(item for item in conflicts if item.severity != "error")
        if blocking:
            return {
                "ok": False,
                "message": self.editor.conflict_summary(blocking),
                "conflicts": [self._conflict(item) for item in conflicts],
                "requiresConfirmation": False,
            }
        if warnings and not allow_warnings:
            message = self.editor.conflict_summary(warnings)
            prefix = "Import requires confirmation. " if self.editor.lang == "en" else "Імпорт потребує підтвердження. "
            return {
                "ok": False,
                "message": prefix + message,
                "conflicts": [self._conflict(item) for item in conflicts],
                "requiresConfirmation": True,
            }

        before_registry = self.editor.registry
        before_profile = before_registry.to_profile()
        result = self.editor.import_profile(text)
        response = self._commit_persisted_mutation(
            result,
            before_registry=before_registry,
            before_profile=before_profile,
            replace_incompatible=True,
        )
        response["requiresConfirmation"] = False
        return response

    def set_language(self, lang: str) -> dict[str, Any]:
        self.editor.set_language(lang)
        return self.snapshot()

    def _blocked_incremental_mutation(self) -> dict[str, Any] | None:
        if not self._profile_write_blocked:
            return None
        if self.recovery_message == "unreadable keymap profile":
            message = (
                "The existing keyboard profile could not be read and was preserved unchanged. "
                "Restore access and restart Accessible Chess, or use Reset all defaults or import a compatible profile to replace it explicitly."
                if self.editor.lang == "en"
                else "Наявний профіль клавіш не вдалося прочитати, тому його збережено без змін. "
                "Відновіть доступ і перезапустіть Accessible Chess або явно замініть профіль через скидання всіх налаштувань чи імпорт сумісного профілю."
            )
        elif self.recovery_message == "invalid keymap profile":
            message = (
                "The existing keyboard profile is invalid and was preserved unchanged. "
                "Use Reset all defaults or import a compatible profile to replace it explicitly."
                if self.editor.lang == "en"
                else "Наявний профіль клавіш некоректний і збережений без змін. "
                "Явно замініть його через скидання всіх налаштувань або імпорт сумісного профілю."
            )
        else:
            message = (
                "Keyboard settings were created by a newer Accessible Chess version and were preserved unchanged. "
                "Use Reset all defaults or import a compatible profile to replace them."
                if self.editor.lang == "en"
                else "Налаштування клавіш створено новішою версією Accessible Chess і збережено без змін. "
                "Щоб замінити їх, скиньте всі налаштування або імпортуйте сумісний профіль."
            )
        return {
            "ok": False,
            "message": message,
            "conflicts": [],
            "requiresConfirmation": False,
        }

    def _commit_persisted_mutation(
        self,
        result,
        *,
        before_registry: ActionRegistry,
        before_profile: Mapping[str, object],
        replace_incompatible: bool = False,
    ) -> dict[str, Any]:
        if not result.ok:
            return self._mutation_result(result)

        # Import currently constructs a validated candidate registry. Fold that
        # profile back into the already-shared registry object before persistence
        # so application dispatch and the keymap editor keep one live authority.
        if self.editor.registry is not before_registry:
            imported_profile = self.editor.registry.to_profile()
            before_registry.replace_profile(imported_profile)
            self.editor.registry = before_registry

        try:
            self._persist(replace_incompatible=replace_incompatible)
        except OSError:
            # Editor mutations happen before disk I/O. Restore the exact prior
            # live profile if persistence fails so runtime dispatch cannot diverge
            # from the unchanged persisted authority. Protected-profile flags are
            # cleared only by a successful _persist(), so they remain intact here.
            before_registry.replace_profile(before_profile)
            self.editor.registry = before_registry
            message = (
                "Keyboard settings could not be saved; previous settings remain active."
                if self.editor.lang == "en"
                else "Не вдалося зберегти налаштування клавіш; попередні налаштування залишаються активними."
            )
            return {
                "ok": False,
                "message": message,
                "conflicts": [],
                "requiresConfirmation": False,
            }

        return self._mutation_result(result)

    def _persist(self, *, replace_incompatible: bool = False) -> None:
        if self._profile_write_blocked and not replace_incompatible:
            raise RuntimeError("protected keymap profile must not be overwritten incrementally")
        self.editor.registry.save(self.path)
        self._profile_write_blocked = False
        self.recovery_message = None

    def _capture_control(self, reason: str, key: str) -> dict[str, Any]:
        if reason == "navigation":
            message = "Tab keeps focus navigation." if self.editor.lang == "en" else "Tab залишає навігацію фокусом."
        else:
            message = "Shortcut capture cancelled." if self.editor.lang == "en" else "Захоплення комбінації скасовано."
        return {
            "captured": False,
            "reason": reason,
            "binding": key,
            "status": "cancelled" if reason == "cancelled" else "navigation",
            "message": message,
            "canSave": False,
            "requiresConfirmation": False,
            "conflicts": [],
        }

    @staticmethod
    def _resolution(item) -> dict[str, Any] | None:
        if item is None:
            return None
        return {
            "actionId": item.action_id,
            "context": item.context.value,
            "binding": item.binding,
            "alias": item.alias,
        }

    @staticmethod
    def _conflict(item) -> dict[str, Any]:
        return {
            "kind": item.kind,
            "actionId": item.action_id,
            "otherActionId": item.other_action_id,
            "context": item.context.value,
            "value": item.value,
            "message": item.message,
            "severity": item.severity,
        }

    def _mutation_result(self, result) -> dict[str, Any]:
        response = self._result(result)
        if result.ok:
            # Return the post-mutation authority snapshot in the same bridge
            # response. The WebView can then atomically replace its synchronous
            # child-surface resolver without a second request that temporarily
            # revives stale/default shortcuts.
            response["snapshot"] = self.snapshot()
        return response

    @classmethod
    def _result(cls, result) -> dict[str, Any]:
        return {
            "ok": result.ok,
            "message": result.message,
            "conflicts": [cls._conflict(item) for item in result.conflicts],
        }
