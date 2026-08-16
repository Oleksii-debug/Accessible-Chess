from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Protocol

from .visual_preferences import VisualPackKind, VisualPackManifest


class VisualPackInstallState(str, Enum):
    AVAILABLE = "available"
    INSTALLED = "installed"
    UPDATE_AVAILABLE = "update_available"
    INCOMPATIBLE = "incompatible"
    DAMAGED = "damaged"


@dataclass(frozen=True)
class VisualPackCatalogEntry:
    """Safe presentation record for a validated visual-pack manifest.

    Manifest/path validation stays in ``VisualPackManifest`` and the actual
    download/staging/integrity/atomic-install work stays behind the catalog port.
    This record contains no executable path and cannot mutate chess state.
    """

    manifest: VisualPackManifest
    state: VisualPackInstallState
    installed_version: str | None = None
    compatible: bool = True
    description: str = ""
    provenance: str = ""

    def __post_init__(self) -> None:
        if self.state is VisualPackInstallState.INCOMPATIBLE and self.compatible:
            raise ValueError("incompatible pack cannot be marked compatible")
        if self.installed_version is not None and not str(self.installed_version).strip():
            raise ValueError("installed_version cannot be blank")
        object.__setattr__(self, "description", str(self.description).strip())
        object.__setattr__(self, "provenance", str(self.provenance).strip())


class VisualPackCatalogPort(Protocol):
    """Provider-neutral visual-pack lifecycle boundary used by presentation.

    Implementations own remote catalog access, bounded download, staging,
    checksum/signature verification, manifest validation and atomic install.
    UI code only requests an operation and refreshes the resulting catalog.
    """

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
        self._port = port
        self._built_in = {
            VisualPackKind.BOARD: str(built_in_board_id).strip().lower(),
            VisualPackKind.PIECES: str(built_in_piece_id).strip().lower(),
        }

    @property
    def available(self) -> bool:
        return self._port is not None

    def snapshot(self) -> dict[str, object]:
        entries = self._entries()
        return {
            "available": self.available,
            "builtInFallback": {
                "board": self._built_in[VisualPackKind.BOARD],
                "pieces": self._built_in[VisualPackKind.PIECES],
            },
            "entries": [self._view(item) for item in entries],
            "accessibleText": (
                f"Доступно пакетів оформлення: {len(entries)}."
                if self.available
                else "Каталог пакетів оформлення не підключено."
            ),
        }

    def install(self, pack_id: str) -> dict[str, object]:
        return self._operate("install", pack_id)

    def update(self, pack_id: str) -> dict[str, object]:
        return self._operate("update", pack_id)

    def uninstall(self, pack_id: str) -> dict[str, object]:
        normalized = str(pack_id).strip().lower()
        entry = self._find(normalized)
        if entry.manifest.pack_id == self._built_in[entry.manifest.kind]:
            return {
                "ok": False,
                "accessibleText": "Вбудований резервний пакет не можна видалити.",
                "entry": self._view(entry),
            }
        return self._operate("uninstall", normalized)

    def _operate(self, operation: str, pack_id: str) -> dict[str, object]:
        if self._port is None:
            return {
                "ok": False,
                "accessibleText": "Керування пакетами оформлення недоступне.",
            }
        entry = self._find(pack_id)
        if not entry.compatible or entry.state in {
            VisualPackInstallState.INCOMPATIBLE,
            VisualPackInstallState.DAMAGED,
        }:
            return {
                "ok": False,
                "accessibleText": f"Пакет {entry.manifest.title} не можна застосувати.",
                "entry": self._view(entry),
            }
        method = getattr(self._port, operation)
        try:
            updated = method(entry.manifest.pack_id)
        except (ValueError, KeyError, OSError):
            return {
                "ok": False,
                "accessibleText": "Не вдалося змінити пакет оформлення.",
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

    def _entries(self) -> tuple[VisualPackCatalogEntry, ...]:
        if self._port is None:
            return ()
        return tuple(
            sorted(
                self._port.list_entries(),
                key=lambda item: (item.manifest.kind.value, item.manifest.title.casefold(), item.manifest.pack_id),
            )
        )

    def _find(self, pack_id: str) -> VisualPackCatalogEntry:
        normalized = str(pack_id).strip().lower()
        for item in self._entries():
            if item.manifest.pack_id == normalized:
                return item
        raise ValueError("unknown visual pack")

    def installed_manifests(self) -> tuple[VisualPackManifest, ...]:
        return tuple(
            item.manifest
            for item in self._entries()
            if item.compatible
            and item.state in {VisualPackInstallState.INSTALLED, VisualPackInstallState.UPDATE_AVAILABLE}
        )

    @staticmethod
    def _view(entry: VisualPackCatalogEntry) -> dict[str, object]:
        manifest = entry.manifest
        installed = entry.state in {
            VisualPackInstallState.INSTALLED,
            VisualPackInstallState.UPDATE_AVAILABLE,
        }
        can_install = entry.compatible and entry.state is VisualPackInstallState.AVAILABLE
        can_update = entry.compatible and entry.state is VisualPackInstallState.UPDATE_AVAILABLE
        can_uninstall = installed
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
