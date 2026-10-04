from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from .visual_preferences import VisualPackKind, VisualPackManifest

_MAX_CATALOG_ENTRIES = 512
_MAX_VERSION_LENGTH = 64
_MAX_DESCRIPTION_LENGTH = 1000
_MAX_PROVENANCE_LENGTH = 1000
_BIDI_FORMAT_CONTROLS = frozenset("\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")


class VisualPackInstallState(str, Enum):
    AVAILABLE = "available"
    INSTALLED = "installed"
    UPDATE_AVAILABLE = "update_available"
    INCOMPATIBLE = "incompatible"
    DAMAGED = "damaged"


def _catalog_text(value: object, label: str, *, max_length: int, allow_empty: bool = True) -> str:
    if type(value) is not str:
        raise ValueError(f"{label} must be text")
    text = value.strip()
    if not text and not allow_empty:
        raise ValueError(f"{label} must not be empty")
    if len(text) > max_length:
        raise ValueError(f"{label} is too long")
    if any(ord(ch) < 32 or ch in _BIDI_FORMAT_CONTROLS for ch in text):
        raise ValueError(f"{label} contains unsafe control text")
    return text


def _install_state(value: object) -> VisualPackInstallState:
    if isinstance(value, VisualPackInstallState):
        return value
    if type(value) is not str:
        raise ValueError("visual pack state must be text")
    try:
        return VisualPackInstallState(value.strip().lower())
    except ValueError as exc:
        raise ValueError("unknown visual pack state") from exc


def _request_pack_id(value: object) -> str | None:
    if type(value) is not str:
        return None
    text = value.strip().lower()
    if not text or len(text) > 64:
        return None
    if any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789._-" for ch in text):
        return None
    return text


@dataclass(frozen=True)
class VisualPackCatalogEntry:
    """Safe presentation record for one validated visual-pack manifest."""

    manifest: VisualPackManifest
    state: VisualPackInstallState
    installed_version: str | None = None
    compatible: bool = True
    description: str = ""
    provenance: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.manifest, VisualPackManifest):
            raise ValueError("catalog manifest must be validated VisualPackManifest")
        state = _install_state(self.state)
        if type(self.compatible) is not bool:
            raise ValueError("catalog compatible flag must be boolean")
        if state is VisualPackInstallState.INCOMPATIBLE and self.compatible:
            raise ValueError("incompatible pack cannot be marked compatible")
        installed_version = self.installed_version
        if installed_version is not None:
            installed_version = _catalog_text(
                installed_version,
                "installed_version",
                max_length=_MAX_VERSION_LENGTH,
                allow_empty=False,
            )
        description = _catalog_text(
            self.description,
            "catalog description",
            max_length=_MAX_DESCRIPTION_LENGTH,
        )
        provenance = _catalog_text(
            self.provenance,
            "catalog provenance",
            max_length=_MAX_PROVENANCE_LENGTH,
        )
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "installed_version", installed_version)
        object.__setattr__(self, "description", description)
        object.__setattr__(self, "provenance", provenance)


class VisualPackCatalogPort(Protocol):
    """Provider-neutral visual-pack lifecycle boundary used by presentation."""

    def list_entries(self) -> tuple[VisualPackCatalogEntry, ...]: ...

    def install(self, pack_id: str) -> VisualPackCatalogEntry: ...

    def update(self, pack_id: str) -> VisualPackCatalogEntry: ...

    def uninstall(self, pack_id: str) -> VisualPackCatalogEntry: ...


class VisualPackCatalogPresentation:
    """Accessible pack-catalog projection with fail-closed lifecycle actions."""

    def __init__(
        self,
        port: VisualPackCatalogPort | None = None,
        *,
        built_in_board_id: str = "classic",
        built_in_piece_id: str = "classic",
    ) -> None:
        board_id = _request_pack_id(built_in_board_id)
        piece_id = _request_pack_id(built_in_piece_id)
        if board_id is None or piece_id is None:
            raise ValueError("built-in visual pack IDs must be stable lowercase IDs")
        self._port = port
        self._built_in = {
            VisualPackKind.BOARD: board_id,
            VisualPackKind.PIECES: piece_id,
        }

    @property
    def available(self) -> bool:
        return self._port is not None

    def snapshot(self) -> dict[str, object]:
        entries, healthy = self._read_entries()
        if self._port is None:
            accessible = "Каталог пакетів оформлення не підключено."
        elif not healthy:
            accessible = "Не вдалося прочитати каталог пакетів оформлення."
        else:
            accessible = f"Доступно пакетів оформлення: {len(entries)}."
        return {
            "available": self.available,
            "healthy": healthy,
            "builtInFallback": {
                "board": self._built_in[VisualPackKind.BOARD],
                "pieces": self._built_in[VisualPackKind.PIECES],
            },
            "entries": [self._view(item) for item in entries],
            "accessibleText": accessible,
        }

    def install(self, pack_id: str) -> dict[str, object]:
        return self._operate("install", pack_id)

    def update(self, pack_id: str) -> dict[str, object]:
        return self._operate("update", pack_id)

    def uninstall(self, pack_id: str) -> dict[str, object]:
        return self._operate("uninstall", pack_id)

    def _operate(self, operation: str, pack_id: object) -> dict[str, object]:
        if self._port is None:
            return {
                "ok": False,
                "accessibleText": "Керування пакетами оформлення недоступне.",
            }
        requested = _request_pack_id(pack_id)
        if requested is None:
            return self._unknown_pack_result()
        entries, healthy = self._read_entries()
        if not healthy:
            return {
                "ok": False,
                "accessibleText": "Не вдалося прочитати каталог пакетів оформлення.",
            }
        entry = next(
            (item for item in entries if item.manifest.pack_id == requested),
            None,
        )
        if entry is None:
            return self._unknown_pack_result()
        if operation == "uninstall" and entry.manifest.pack_id == self._built_in[entry.manifest.kind]:
            return {
                "ok": False,
                "accessibleText": "Вбудований резервний пакет не можна видалити.",
                "entry": self._view(entry),
            }
        if not entry.compatible or entry.state in {
            VisualPackInstallState.INCOMPATIBLE,
            VisualPackInstallState.DAMAGED,
        }:
            return {
                "ok": False,
                "accessibleText": f"Пакет {entry.manifest.title} не можна застосувати.",
                "entry": self._view(entry),
            }
        expected_states = {
            "install": {VisualPackInstallState.AVAILABLE},
            "update": {VisualPackInstallState.UPDATE_AVAILABLE},
            "uninstall": {
                VisualPackInstallState.INSTALLED,
                VisualPackInstallState.UPDATE_AVAILABLE,
            },
        }
        if operation not in expected_states or entry.state not in expected_states[operation]:
            return {
                "ok": False,
                "accessibleText": "Ця дія зараз недоступна для вибраного пакета.",
                "entry": self._view(entry),
            }
        method = getattr(self._port, operation)
        try:
            updated = method(entry.manifest.pack_id)
        except Exception:
            return {
                "ok": False,
                "accessibleText": "Не вдалося змінити пакет оформлення.",
                "entry": self._view(entry),
            }
        if (
            not isinstance(updated, VisualPackCatalogEntry)
            or updated.manifest.pack_id != entry.manifest.pack_id
            or updated.manifest.kind is not entry.manifest.kind
        ):
            return {
                "ok": False,
                "accessibleText": "Не вдалося підтвердити зміну пакета оформлення.",
                "entry": self._view(entry),
            }
        labels = {
            "install": "встановлено",
            "update": "оновлено",
            "uninstall": "видалено",
        }
        return {
            "ok": True,
            "accessibleText": f"Пакет {updated.manifest.title} {labels[operation]}.",
            "entry": self._view(updated),
        }

    def _read_entries(self) -> tuple[tuple[VisualPackCatalogEntry, ...], bool]:
        if self._port is None:
            return (), True
        try:
            raw = self._port.list_entries()
            if type(raw) is not tuple or len(raw) > _MAX_CATALOG_ENTRIES:
                return (), False
            seen: set[str] = set()
            entries: list[VisualPackCatalogEntry] = []
            for item in raw:
                if not isinstance(item, VisualPackCatalogEntry):
                    return (), False
                if item.manifest.pack_id in seen:
                    return (), False
                seen.add(item.manifest.pack_id)
                entries.append(item)
            entries.sort(
                key=lambda item: (
                    item.manifest.kind.value,
                    item.manifest.title.casefold(),
                    item.manifest.pack_id,
                )
            )
            return tuple(entries), True
        except Exception:
            return (), False

    @staticmethod
    def _unknown_pack_result() -> dict[str, object]:
        return {
            "ok": False,
            "accessibleText": "Пакет оформлення не знайдено.",
        }

    def installed_manifests(self) -> tuple[VisualPackManifest, ...]:
        entries, healthy = self._read_entries()
        if not healthy:
            return ()
        return tuple(
            item.manifest
            for item in entries
            if item.compatible
            and item.state
            in {VisualPackInstallState.INSTALLED, VisualPackInstallState.UPDATE_AVAILABLE}
        )

    def _view(self, entry: VisualPackCatalogEntry) -> dict[str, object]:
        manifest = entry.manifest
        installed = entry.state in {
            VisualPackInstallState.INSTALLED,
            VisualPackInstallState.UPDATE_AVAILABLE,
        }
        can_install = entry.compatible and entry.state is VisualPackInstallState.AVAILABLE
        can_update = entry.compatible and entry.state is VisualPackInstallState.UPDATE_AVAILABLE
        can_uninstall = installed and manifest.pack_id != self._built_in[manifest.kind]
        status_text = {
            VisualPackInstallState.AVAILABLE: "Доступний для встановлення",
            VisualPackInstallState.INSTALLED: "Встановлено",
            VisualPackInstallState.UPDATE_AVAILABLE: "Доступне оновлення",
            VisualPackInstallState.INCOMPATIBLE: "Несумісний",
            VisualPackInstallState.DAMAGED: "Пошкоджений",
        }[entry.state]
        metadata = [manifest.title, f"версія {manifest.version}", status_text]
        if manifest.author:
            metadata.append(f"автор {manifest.author}")
        metadata.append(f"ліцензія {manifest.license_id}")
        if entry.provenance:
            metadata.append(f"походження {entry.provenance}")
        return {
            "id": manifest.pack_id,
            "title": manifest.title,
            "version": manifest.version,
            "kind": manifest.kind.value,
            "author": manifest.author,
            "license": manifest.license_id,
            "description": entry.description,
            "provenance": entry.provenance,
            "state": entry.state.value,
            "installedVersion": entry.installed_version,
            "compatible": entry.compatible,
            "canInstall": can_install,
            "canUpdate": can_update,
            "canUninstall": can_uninstall,
            "statusText": status_text,
            "accessibleText": "; ".join(metadata) + ".",
        }
